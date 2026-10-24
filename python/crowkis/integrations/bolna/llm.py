"""CrowkisLLM: the cache in front of one of Bolna's own LLM classes."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Iterator, List, Optional, Sequence

from bolna.llms.types import LatencyData, LLMStreamChunk

from ...voice import TurnDecision
from ...voice_async import AsyncVoiceSession
from ...voice_turns import _earlier_callers, _field, _instructions
from .synthesizer import AUDIO_CONCERN, CallLinks
from .turn_filter import GenerateCall, TurnFilter

SYSTEM_ROLES = ("system", "developer")
ASSISTANT_ROLE = "assistant"
DEFAULT_BUFFER_SIZE = 40
RECORD_CONCERN = "record"
LOOKUP_CONCERN = "lookup"
CLOSE_CONCERN = "close"


@dataclass
class PendingAnswer:
    """A finished model answer, held until Bolna's history shows it in full.

    Bolna writes a reply to its history only once the audio went out, and trims it when the
    caller talks over it. So the answer is saved only when the history row for its
    ``response_uid`` equals the text; anything else (no row, a trimmed row, another reply)
    is dropped. With no task manager to ask (``history`` is None) the answer is trusted and
    saved. Over-dropping only costs cache hits."""

    decision: TurnDecision
    text: str
    instructions: Optional[str]
    response_uid: Optional[str]
    sequence_id: Optional[int] = None

    def committed_in(self, history: Optional[Sequence[Any]]) -> bool:
        """Whether Bolna's history holds this answer, whole."""
        if history is None:
            return True
        if self.response_uid is None:
            return False
        for row in reversed(history):
            if row.get("role") == ASSISTANT_ROLE and row.get("response_uid") == self.response_uid:
                return _squash(row.get("content")) == _squash(self.text)
        return False


def _squash(text: Any) -> str:
    """Text with its whitespace made single spaces, so spacing never decides a match."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def _served_chunks(text: str, *, sequence_id: Optional[int], buffer_size: int,
                   synthesize: bool) -> List[LLMStreamChunk]:
    """A served answer shaped the way Bolna's own LLMs stream one, so the speech side cannot
    tell it from a model's: synthesised text is cut at the last space once about ``buffer_size``
    characters wait, an unsynthesised answer goes whole, and the last chunk ends the stream."""
    pieces = _pieces(text, buffer_size) if synthesize else [text]
    last = len(pieces) - 1
    return [LLMStreamChunk(data=piece, end_of_stream=index == last, latency=LatencyData(sequence_id=sequence_id))
            for index, piece in enumerate(pieces)]


def _pieces(text: str, buffer_size: int) -> List[str]:
    words = text.split()
    if not words:
        return [text]
    pieces: List[str] = []
    waiting: List[str] = []
    for word in words:
        waiting.append(word)
        if len(" ".join(waiting)) >= buffer_size:
            pieces.append(" ".join(waiting))
            waiting = []
    if waiting:
        pieces.append(" ".join(waiting))
    return pieces


def _leading_system(messages: List[Any]) -> List[Any]:
    """The app's own instructions: the system messages before the conversation starts."""
    leading: List[Any] = []
    for message in messages:
        if _field(message, "role") not in SYSTEM_ROLES:
            break
        leading.append(message)
    return leading


class CrowkisLLM:
    """Decorator around a Bolna LLM: a caller's turn is answered from the cache when it can be.

    One instance serves one call (Bolna builds one LLM per call), so it owns one Crowkis
    session and no caller's details are ever shared. ``generate_stream`` is the only
    method that changes; every other attribute and method is the wrapped LLM's own.
    The session is an ``AsyncVoiceSession``: Bolna is fully async, so a sync one is not supported.

    A turn goes through a ``TurnFilter`` (turns Crowkis never touches go straight to the
    wrapped LLM), then the session decides: a hit is streamed as Bolna chunks, a miss is
    answered by the wrapped LLM reading the question alone (or the whole call when the
    answer must stay private) and its answer is held as a ``PendingAnswer`` until Bolna's
    history shows it was spoken in full. Every Crowkis failure goes through the call's
    ``FailOpenBoundary`` and the wrapped LLM answers instead.

    With a ``CallLinks`` shared with the call's ``CrowkisSynthesizer``, it also tells the
    synthesizer what each answer's audio is: a cached clip to play, or audio to keep once
    the answer is saved word for word."""

    def __init__(self, inner: Any, session: AsyncVoiceSession, *, task_manager: Any = None,
                 owns_session: bool = False, turn_filter: Optional[TurnFilter] = None,
                 links: Optional[CallLinks] = None) -> None:

        self._inner = inner
        self._session = session
        self._task_manager = task_manager
        self._owns_session = owns_session
        self._filter = turn_filter or TurnFilter.standard()
        self._plan = (links or CallLinks()).plan_for(task_manager)
        self._boundary = self._plan.boundary  # the call's one boundary, shared with its synthesizer
        self._plan.bind_session(session)
        self._pending: Optional[PendingAnswer] = None
        self._closed = False
        self._chain_diverged = False

    def __getattr__(self, name: str) -> Any:
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    @property
    def failures(self) -> Any:
        """How many times each Crowkis concern failed and was skipped."""
        return self._boundary.failures

    async def generate_stream(self, messages: List[Any], synthesize: bool = True, request_json: bool = False,
                              meta_info: Optional[dict] = None, tool_choice: Any = None,
                              tools: Any = None) -> AsyncIterator[LLMStreamChunk]:
        """Bolna's per-turn call: cached chunks on a hit, the wrapped LLM's own chunks otherwise."""
        await self._settle_pending()
        call = GenerateCall(messages, synthesize, request_json, meta_info, tool_choice, tools,
                            self._agent_type(), self._task_manager is not None)
        source = await self._source(call)
        async with contextlib.aclosing(source):
            async for chunk in source:
                yield chunk

    def cancel_in_flight_response(self) -> None:
        """Barge-in: the Crowkis turn is dropped too, so its answer is never saved."""
        self._session.cancel()
        self._plan.drop_all()
        self._inner.cancel_in_flight_response()

    async def close(self) -> None:
        """End of call: save what Bolna spoke in full, then release the wrapped LLM."""
        if self._closed:
            return
        self._closed = True
        await self._settle_pending()
        if self._owns_session:
            await self._boundary.attempt(CLOSE_CONCERN, self._session.close())
        await self._inner.close()

    async def _source(self, call: GenerateCall) -> AsyncIterator[LLMStreamChunk]:
        """The stream that answers this call: the wrapped LLM untouched, the cache, or the model."""
        if self._filter.bypass_rule(call) is not None:
            self._hear(call.caller_text)
            return self._ask_inner(call, call.messages)
        decision = await self._decide(call)
        if decision is None:
            return self._ask_inner(call, call.messages)
        if decision.needs_model or not decision.text:
            return self._answer_with_model(call, decision)
        return self._serve(call, decision)

    async def _decide(self, call: GenerateCall) -> Optional[TurnDecision]:
        for said in _earlier_callers(list(call.messages)):
            self._hear(said)
        return await self._boundary.attempt(LOOKUP_CONCERN, self._session.decide(call.last_text))

    async def _serve(self, call: GenerateCall, decision: TurnDecision) -> AsyncIterator[LLMStreamChunk]:
        self._inner.invalidate_response_chain()
        self._chain_diverged = True
        await self._arrange_clip(call, decision)
        chunks = _served_chunks(decision.text, sequence_id=call.meta.get("sequence_id"),
                                buffer_size=getattr(self._inner, "buffer_size", DEFAULT_BUFFER_SIZE),
                                synthesize=call.synthesize)
        with self._cancel_on_barge_in():
            for chunk in chunks:
                yield chunk

    async def _arrange_clip(self, call: GenerateCall, decision: TurnDecision) -> None:
        """Tell the synthesizer how to speak a served answer: its cached clip, or its own voice
        and then keep that audio. An answer filled with this caller's values uses neither."""
        if not decision.audio_shareable:
            return
        sequence_id = call.meta.get("sequence_id")
        clip = await self._plan.fetch(decision.text)
        if clip:
            self._plan.play(sequence_id, decision.text, clip)
        else:
            self._plan.keep_served(sequence_id, decision.text)

    async def _answer_with_model(self, call: GenerateCall, decision: TurnDecision) -> AsyncIterator[LLMStreamChunk]:
        messages = self._model_messages(call, decision)
        sequence_id = call.meta.get("sequence_id")
        if decision.needs_model and decision.cacheable:
            self._plan.keep_answer(sequence_id)
        pieces: List[str] = []
        went_to_tool = False
        with self._cancel_on_barge_in(lambda: not went_to_tool):
            async for chunk in self._ask_inner(call, messages):
                if getattr(chunk, "is_function_call", False):
                    went_to_tool = True
                elif isinstance(getattr(chunk, "data", None), str):
                    pieces.append(chunk.data)
                yield chunk
        if went_to_tool:
            self._plan.drop(sequence_id)
        elif decision.needs_model:
            self._pending = PendingAnswer(decision, " ".join(" ".join(pieces).split()),
                                          _instructions(list(call.messages)) or None,
                                          call.meta.get("response_uid"), sequence_id)

    def _model_messages(self, call: GenerateCall, decision: TurnDecision) -> List[Any]:
        """The whole call, or the app's instructions plus only what Crowkis chose to share."""
        if decision.messages is None:
            return call.messages
        self._inner.invalidate_response_chain()
        self._chain_diverged = True
        return _leading_system(list(call.messages)) + list(decision.messages)

    async def _ask_inner(self, call: GenerateCall, messages: List[Any]) -> AsyncIterator[LLMStreamChunk]:
        if messages is call.messages and self._chain_diverged:
            # A chained call sends only the newest messages, so it must not continue a response
            # the model made without the call's context.
            self._inner.invalidate_response_chain()
            self._chain_diverged = False
        stream = self._inner.generate_stream(
            messages, synthesize=call.synthesize, request_json=call.request_json,
            meta_info=call.meta_info, tool_choice=call.tool_choice, tools=call.tools)
        async with contextlib.aclosing(stream):
            async for chunk in stream:
                yield chunk

    async def _settle_pending(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        recorded = pending.committed_in(self._history())
        if recorded:
            await self._boundary.attempt(
                RECORD_CONCERN, self._session.record(pending.decision, pending.text, system=pending.instructions))
        await self._plan.settle(pending.sequence_id, pending.text, await self._clip_shareable(pending, recorded))

    async def _clip_shareable(self, pending: PendingAnswer, recorded: bool) -> bool:
        """Whether the audio of a settled answer may be shared: only an answer saved word for word
        (a template says this caller's values aloud), and not one the server holds until it vouches."""
        decision = pending.decision
        if not (recorded and decision.stored and decision.cacheable):
            return False
        holds = await self._boundary.attempt(AUDIO_CONCERN, self._holds_new_answers())
        return holds is False

    async def _holds_new_answers(self) -> bool:
        """Whether the server's decision engine holds a new answer until it vouches for it: its
        audio is then made when the answer is first served, never before."""
        agent = self._session.agent
        return await asyncio.to_thread(lambda: agent.decides() and agent._holds)

    def _history(self) -> Optional[list]:
        """Bolna's committed history; None when there is no task manager to ask."""
        if self._task_manager is None:
            return None
        return getattr(self._task_manager, "history", None) or []

    def _agent_type(self) -> Optional[str]:
        config = getattr(self._task_manager, "task_config", None) or {}
        llm_agent = (config.get("tools_config") or {}).get("llm_agent") or {}
        return llm_agent.get("agent_type")

    def _hear(self, caller_said: Optional[str]) -> None:
        if caller_said:
            self._session._heard(caller_said)

    @contextlib.contextmanager
    def _cancel_on_barge_in(self, still_cancellable: Callable[[], bool] = lambda: True) -> Iterator[None]:
        """Cancel the Crowkis turn if the stream is closed; not once Bolna has moved on (a tool call)."""
        try:
            yield
        except (asyncio.CancelledError, GeneratorExit):
            if still_cancellable():
                self._session.cancel()
            raise
