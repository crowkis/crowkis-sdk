"""CrowkisLLM: the cache in front of one of Bolna's own LLM classes."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator, Callable, Iterator, List, Optional

from bolna.llms.types import LLMStreamChunk

from ...voice import TurnDecision
from ...voice_turns import _earlier_callers, _field, _instructions
from .fail_open import FailOpenBoundary
from .pending_answer import PendingAnswer
from .served_reply import ServedReply
from .session_port import SessionPort
from .turn_filter import GenerateCall, TurnFilter

SYSTEM_ROLES = ("system", "developer")
DEFAULT_BUFFER_SIZE = 40


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

    A turn goes through a ``TurnFilter`` (turns Crowkis never touches go straight to the
    wrapped LLM), then the session decides: a hit is streamed as Bolna chunks, a miss is
    answered by the wrapped LLM reading the question alone (or the whole call when the
    answer must stay private) and its answer is held as a ``PendingAnswer`` until Bolna's
    history shows it was spoken in full. Every Crowkis failure goes through one
    ``FailOpenBoundary`` and the wrapped LLM answers instead."""

    def __init__(self, inner: Any, session: Any, *, task_manager: Any = None, owns_session: bool = False,
                 turn_filter: Optional[TurnFilter] = None, boundary: Optional[FailOpenBoundary] = None) -> None:
        self._inner = inner
        self._port = SessionPort(session)
        self._task_manager = task_manager
        self._owns_session = owns_session
        self._filter = turn_filter or TurnFilter.standard()
        self._boundary = boundary or FailOpenBoundary()
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
        self._port.cancel()
        self._inner.cancel_in_flight_response()

    async def close(self) -> None:
        """End of call: save what Bolna spoke in full, then release the wrapped LLM."""
        if self._closed:
            return
        self._closed = True
        await self._settle_pending()
        if self._owns_session:
            await self._boundary.attempt("close", self._port.close())
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
        return await self._boundary.attempt("lookup", self._port.decide(call.last_text))

    async def _serve(self, call: GenerateCall, decision: TurnDecision) -> AsyncIterator[LLMStreamChunk]:
        self._inner.invalidate_response_chain()
        self._chain_diverged = True
        reply = ServedReply(decision.text, sequence_id=call.meta.get("sequence_id"),
                            buffer_size=getattr(self._inner, "buffer_size", DEFAULT_BUFFER_SIZE),
                            synthesize=call.synthesize)
        with self._cancel_on_barge_in():
            for chunk in reply.chunks():
                yield chunk

    async def _answer_with_model(self, call: GenerateCall, decision: TurnDecision) -> AsyncIterator[LLMStreamChunk]:
        messages = self._model_messages(call, decision)
        pieces: List[str] = []
        went_to_tool = False
        with self._cancel_on_barge_in(lambda: not went_to_tool):
            async for chunk in self._ask_inner(call, messages):
                if getattr(chunk, "is_function_call", False):
                    went_to_tool = True
                elif isinstance(getattr(chunk, "data", None), str):
                    pieces.append(chunk.data)
                yield chunk
        if not went_to_tool and decision.needs_model:
            self._pending = PendingAnswer(decision, " ".join(" ".join(pieces).split()),
                                          _instructions(list(call.messages)) or None,
                                          call.meta.get("response_uid"))

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
        if pending is not None:
            await pending.settle(self._history(), self._record)

    async def _record(self, decision: TurnDecision, text: str, instructions: Optional[str]) -> None:
        await self._boundary.attempt("record", self._port.record(decision, text, instructions))

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
            self._port.heard(caller_said)

    @contextlib.contextmanager
    def _cancel_on_barge_in(self, still_cancellable: Callable[[], bool] = lambda: True) -> Iterator[None]:
        """Cancel the Crowkis turn if the stream is closed; not once Bolna has moved on (a tool call)."""
        try:
            yield
        except (asyncio.CancelledError, GeneratorExit):
            if still_cancellable():
                self._port.cancel()
            raise
