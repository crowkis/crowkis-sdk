"""What every voice framework adapter needs, with no framework in it.

Two pieces, driven by plain events, that a framework adapter (Pipecat, LiveKit, a
custom loop) feeds from its own frames or callbacks:

AudioClips      keeps the spoken audio of an answer the cache shares, so the next hit
                skips the TTS too. A TTS run's audio belongs to the slot the run started
                with, so a clip is never stored under another answer's text; it is kept
                only when the TTS said that text (or the run is trusted by its order),
                and only once the answer's text is ruled shareable. Events: reserve /
                release / expect / vouch / settle, tts_started / tts_text / tts_audio /
                tts_stopped, interrupted.

AnswerPairing   hands each complete model answer to the session with the context it was
                generated from. The LLM answers contexts in the order it receives them,
                so each response is matched to its context: a caller's answer is paired
                with the question that is that context's last user message, and only
                while no tool is in flight; one that could be a tool's late answer is
                held until a later context settles it, and dropped if none does. A tool
                that never answers stops holding answers once the caller has moved on
                twice. An answer cut off by a barge-in is never stored. Events:
                queue_context, caller_moved_on, response_start / response_text /
                response_end, tool_call, tools_done, tool_result, interrupted.

Both are written as mixins over state that lives on the adapter's own objects (the
Pipecat processors keep their attributes), and work as plain objects too.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import collections
from typing import Any, Awaitable, Callable, Optional

from .agent import _store_later, _tts_key
from .client import CrowkisError
from .voice import _words

# Same tool name and key rule as Agent.speak(): a clip is shared with speak() when it
# names the same format (audio_format="pcm16-<rate>").
TTS_TOOL = "crowkis.tts"

# Answered caller turns a tool may say nothing through before it is taken as hung, and
# how many silent tools are remembered at most.
_HUNG_AFTER = 2
_MAX_TOOLS = 4
# Answers whose clip or ruling is still waiting for the other. One turn is in flight at
# a time; a few cover a barge-in that leaves one behind.
_WAITING = 4
# TTS runs that may be reserved ahead of the one playing.
_RUNS_AHEAD = 16

AnswerReport = Optional[Callable[[dict], Awaitable[Any]]]


def _field(message: Any, name: str) -> Any:
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def _last_user(messages: list) -> tuple:
    """The last user message's text, and the messages after it."""
    for index in range(len(messages) - 1, -1, -1):
        if _field(messages[index], "role") == "user":
            return _field(messages[index], "content") or "", messages[index + 1:]
    return None, list(messages)


def _earlier_callers(messages: list) -> list:
    """What the caller said before the last user message, as text (a message's content
    may be a list of parts)."""
    index = max((i for i, m in enumerate(messages) if _field(m, "role") == "user"), default=-1)
    said = []
    for message in messages[:max(index, 0)]:
        if _field(message, "role") != "user":
            continue
        content = _field(message, "content")
        if isinstance(content, list):
            content = " ".join(str(_field(part, "text") or "") for part in content)
        said.append(content if isinstance(content, str) else "")
    return said


def _tool_context(messages: list) -> bool:
    """Whether a context carries a tool call or a tool's result after its last user message."""
    _, after = _last_user(messages)
    return any(
        _field(m, "role") in ("tool", "function") or _field(m, "tool_calls") or _field(m, "function_call")
        or _field(m, "type") in ("function_call", "function_call_output", "tool_use", "tool_result")
        for m in after
    )


def _instructions(messages: list) -> str:
    """The system / developer messages in what the model read, as one text."""
    parts = []
    for message in messages or []:
        if _field(message, "role") in ("system", "developer"):
            content = _field(message, "content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):  # [{"type": "text", "text": ...}, ...]
                parts.extend(str(_field(p, "text") or "") for p in content)
    return "\n".join(p for p in parts if p)


def _remember(waiting: dict, key: str, value: Any) -> None:
    waiting.pop(key, None)
    waiting[key] = value
    while len(waiting) > _WAITING:
        waiting.pop(next(iter(waiting)))


class AudioClips:
    """The clip-keeping half of an adapter (see the module docstring)."""

    def _init_clips(self, session: Any, sample_rate: int) -> None:
        self._session = session
        self.sample_rate = sample_rate
        self._pcm = bytearray()
        # By answer text: finished clips waiting for a ruling, and rulings waiting for
        # their clip. The TTS can finish before or after the write-back has ruled.
        self._clips: dict = {}
        self._rulings: dict = {}
        # One slot per TTS run still to come, in the order the runs will happen: [text].
        # A run's audio belongs to the slot it starts with, never to whatever text was
        # named last, so a clip cannot be stored under another answer's text.
        self._runs: collections.deque = collections.deque()
        self._run: Optional[list] = None  # the slot of the TTS run in progress
        self._unsynced = False
        self._spoken: list = []  # what that run said, where the TTS reports it

    def _key(self, text: str) -> str:
        # The basic cache key names the sample rate too, so a 16 kHz bot never plays a
        # clip made for a 24 kHz one (it used to be the voice and the text only).
        return _tts_key(text, self._labels())

    def _labels(self) -> tuple:
        """Voice, language, speed and format: a clip is reused only when all match.
        The format names the sample rate, so a 16 kHz bot never gets a 24 kHz clip."""
        session = self._session
        audio_format = session.audio_format if session.audio_format != "default" else f"pcm16-{self.sample_rate}"
        return (session.voice, session.language, str(session.speed), audio_format)

    def _uses_audio_cache(self, text: str) -> bool:
        """The agent's rule for the server's audio cache (Voice add-on), the same as `speak`."""
        usable = getattr(self._session.agent, "_audio_cache_usable", None)
        return bool(usable and usable(text, self._labels()))

    async def get(self, text: str) -> Optional[bytes]:
        if getattr(self._session, "_text_only", False):
            return None  # no voice id to key a clip on (voice_session() with no voice)
        if not self.sample_rate:
            return None  # no TTS has said its sample rate: no clip could be played right
        agent = self._session.agent
        if self._uses_audio_cache(text):
            try:
                clip = await asyncio.to_thread(agent._client.caudioget, text, *self._labels(), tenant=agent.tenant)
            except CrowkisError as err:
                use, _ = agent._audio_cache_failed(err)
                if use:
                    return None
            else:
                agent._audio_v2 = True
                return clip or None
        try:
            raw = await asyncio.to_thread(agent._client.ctoolget, TTS_TOOL, self._key(text), tenant=agent.tenant)
        except Exception as err:  # noqa: BLE001 — a failed read is a miss, never the end of the turn
            agent._audio_cache_error("read", err)
            return None
        if not raw:
            return None
        # Strict: a damaged clip is a miss, never noise played to the caller.
        try:
            return base64.b64decode(raw, validate=True) or None
        except (ValueError, binascii.Error):
            return None

    def expect(self, text: str, *, shareable: Optional[bool] = None) -> None:
        """Name the answer that the next TTS run speaks.

        ``shareable=True`` for an answer the cache just served: its clip may be stored.
        Left out for a new answer: its clip waits for ``settle``. A run named here is
        trusted by its order; naming another before it starts replaces it."""
        for waiting in [slot for slot in self._runs if slot[1]]:
            self._runs.remove(waiting)  # its run never happened: no slot is left behind
        self.reserve(text, trusted=True)
        if shareable is not None:
            _remember(self._rulings, text, shareable)

    def reserve(self, text: Optional[str] = None, *, trusted: bool = False) -> list:
        """Hold the place of a TTS run that is coming, in stream order; its text can be
        filled in later (``slot[0] = text``), before the run ends. Unless ``trusted``,
        its clip is kept only when the TTS reports having spoken that text."""
        slot = [text, trusted]
        self._runs.append(slot)
        if len(self._runs) > _RUNS_AHEAD:
            # ponytail: far more runs waiting than a call ever has; rather than guess which
            # run is which, keep no clip until a barge-in resets the order.
            self._runs.clear()
            self._unsynced = True
        return slot

    def release(self, slot: list) -> None:
        """A reserved run that will not happen (an answer with nothing to speak)."""
        if slot in self._runs:
            self._runs.remove(slot)

    def vouch(self, text: str) -> None:
        """An answer the cache served: its clip may be stored once its own run ends."""
        _remember(self._rulings, text, True)

    async def settle(self, text: str, shareable: bool) -> None:
        """The write-back's ruling on a new answer: store its clip, or drop it."""
        clip = self._clips.pop(text, None)
        if clip is None:
            _remember(self._rulings, text, shareable)
        elif shareable:
            await self._store(text, clip)

    # -- TTS events --------------------------------------------------------------------

    def interrupted(self) -> None:
        """A barge-in: the run in progress and every reserved run are gone."""
        self._pcm, self._run, self._spoken, self._unsynced = bytearray(), None, [], False
        self._runs.clear()

    def tts_started(self) -> None:
        """A TTS run starts (one per answer, not per sentence): a new clip, for the next slot.
        A clip replayed from the cache has no run around it, so it never starts one."""
        self._pcm, self._spoken = bytearray(), []
        self._run = self._runs.popleft() if self._runs else None

    def tts_text(self, text: Optional[str]) -> None:
        """Words the run in progress spoke, where the TTS reports them."""
        if self._run is not None:
            self._spoken.append(text or "")

    def tts_audio(self, pcm: bytes) -> None:
        self._pcm += pcm

    async def tts_stopped(self) -> None:
        await self._finish_clip()

    async def _finish_clip(self) -> None:
        """The audio of a TTS run is complete: it belongs to the slot the run started with."""
        run, self._run = self._run, None
        text, clip, spoken = (run[0] if run else None), bytes(self._pcm), _words(" ".join(self._spoken))
        self._pcm, self._spoken = bytearray(), []
        if not (text and clip) or self._unsynced:
            return
        if spoken and spoken != _words(text)[:len(spoken)]:
            return  # the run said something else: never store it under this text
        if not spoken and not run[1]:
            return  # fail closed: the TTS did not say what it spoke
        ruling = self._rulings.pop(text, None)
        if ruling is None:
            _remember(self._clips, text, clip)
        elif ruling:
            await self._store(text, clip)

    async def _store(self, text: str, clip: bytes) -> None:
        if getattr(self._session, "_text_only", False):
            return  # no voice id to key a clip on (voice_session() with no voice)
        if not self.sample_rate:
            return  # no TTS has said its sample rate: the clip's format is unknown
        agent = self._session.agent
        if getattr(agent, "_audio_v2", None) is True and self._uses_audio_cache(text):
            # In the background: the next frame is never held for a store.
            ms = len(clip) * 1000 // (self.sample_rate * 2) if self.sample_rate else None
            _store_later(
                agent._client.caudioset, text, *self._labels(), bytes(clip),
                ex=self._session.ttl, ms=ms, tenant=agent.tenant,
            )
            return
        try:
            await asyncio.to_thread(
                agent._client.ctoolset, TTS_TOOL, self._key(text), base64.b64encode(clip).decode("ascii"),
                ex=self._session.ttl, tenant=agent.tenant,
            )
        except Exception as err:  # noqa: BLE001 — a failed write only costs a later hit
            agent._audio_cache_error("written", err)


class AnswerPairing:
    """The answer-pairing half of an adapter (see the module docstring).

    ``gate`` is the adapter's turn gate: any object with ``asked`` (a deque of the
    contexts sent to the LLM, oldest first: ``(kind, turn, question, messages)`` with kind
    "caller" or "tool", or None for one nobody can be paired with), and ``question`` /
    ``messages`` (for a gate that keeps no queue). ``audio`` is an AudioClips.
    """

    def _init_pairing(self, session: Any, gate: Any, audio: Any, on_answer: AnswerReport = None) -> None:
        self._session = session
        self._gate = gate
        self._audio = audio
        self._on_answer = on_answer
        self._parts: Optional[list] = None
        self._bound: Optional[tuple] = None  # the context the response in progress was generated from
        self._held = False  # that response could be a tool's late answer: hold it until settled
        self._calling = False  # the response in progress asked for a tool
        self._pending: list = []  # (turn, question, messages) of tool calls whose answer is still to come
        self._moves = 0  # caller turns answered, unrecorded, while a tool said nothing
        self._hung: list = []  # tools taken as hung; a result from one re-arms it
        self._deferred: Optional[tuple] = None  # (context, answer) of a held response
        self._slot: Optional[list] = None  # the audio run reserved for the response in progress

    async def _report_answer(self, info: dict) -> None:
        """Tell the app what happened to an answer. Adapters override this to turn the
        callback's return value into their own frames."""
        if self._on_answer is not None:
            await self._on_answer(info)

    # -- events --------------------------------------------------------------------------

    async def response_start(self) -> None:
        """The LLM starts a response. Its TTS run is reserved in stream order; a gate with
        no queue of contexts keeps the original contract: the run is trusted by its order."""
        self._slot = self._audio.reserve(trusted=getattr(self._gate, "asked", None) is None)
        await self._start()

    def response_text(self, text: str) -> None:
        if self._parts is not None:
            self._parts.append(text)

    def speak_requested(self, text: str) -> None:
        """A text the TTS is asked to say directly (a served answer, a fallback): its run, in order."""
        self._audio.reserve(text)

    def tool_call(self) -> None:
        """The response in progress asked for a tool."""
        self._calling = True

    def tools_done(self) -> None:
        """No answer will follow the tools in flight (cancelled, or a result that does not
        run the LLM). Then call ``_settle(True)``."""
        self._pending.clear()
        self._hung.clear()

    def tool_result(self) -> None:
        """A tool's result that runs the LLM again. From a tool taken as hung: what follows
        is its answer after all."""
        if not self._pending and self._hung:
            self._pending.append(self._hung.pop(0))

    def interrupted(self) -> None:
        """A barge-in: the response in progress is never stored. Then call ``_settle(False)``."""
        self._parts, self._bound, self._calling, self._held, self._slot = None, None, False, False, None

    async def response_end(self) -> Optional[tuple]:
        """The response is complete. Returns ``(context, answer)`` to record with
        ``_record`` once the adapter has passed the end of the response on, or None when
        there is nothing to record now (a tool call, a held answer, an unpaired one)."""
        if self._parts is None:
            return None
        answer, self._parts = "".join(self._parts).strip(), None
        bound, self._bound = self._bound, None
        calling, self._calling = self._calling, False
        slot, self._slot = self._slot, None
        if slot is not None and answer:
            slot[0] = answer  # its clip waits for the ruling below
        elif slot is not None:
            self._audio.release(slot)
        if bound is not None and calling:
            # Nothing to record until the tool's result is answered.
            if not self._pending:
                self._moves = 0
            self._pending = (self._pending + [bound[1:]])[-_MAX_TOOLS:]
            await self._audio.settle(answer, False)
        elif bound is not None and bound[0] == "caller" and self._held:
            self._deferred = (bound, answer)
        elif bound is not None:
            return bound, answer
        else:
            await self._audio.settle(answer, False)
        return None

    def queue_context(self, messages: list) -> bool:
        """Queue a context the LLM will answer that the caller did not just say. No await:
        the caller pushes it right after. True when a held answer is now known to be the
        caller's own (the tool's answer comes from this context): settle it then."""
        if not _tool_context(messages):
            self._gate.asked.append(None)
            return False
        question, _ = _last_user(messages)
        tool = next((t for t in self._pending if t[1] == question), None)
        if tool is not None:
            self._pending.remove(tool)
        self._gate.asked.append(("tool", tool[0] if tool else None, question, messages))
        return True

    async def caller_moved_on(self) -> None:
        """A new caller turn: a held response can no longer be told apart from a tool's.
        A tool that has said nothing while two of the caller's turns were answered is
        taken as hung, so it stops holding the call's answers; a result from it later
        re-arms it."""
        if self._pending and self._deferred is not None:
            # The caller's previous turn was answered while the tool said nothing. Only such
            # turns count: a tool can still answer, without its context seen, across turns
            # that were merely asked. The queue of silent tools is capped instead.
            self._moves += 1
        if self._pending and self._moves >= _HUNG_AFTER:
            self._hung, self._pending, self._moves = self._pending[-_MAX_TOOLS:], [], 0
        await self._settle(False)

    # -- the pairing ---------------------------------------------------------------------

    async def _start(self) -> None:
        self._parts, self._held = [], False
        asked = getattr(self._gate, "asked", None)
        if asked is None:
            # A gate that keeps no queue of contexts: pair with its current question, as before.
            self._bound = ("caller", None, self._gate.question, self._gate.messages)
            return
        if self._deferred is not None:
            # Two responses with no context between them while a tool was in flight:
            # either could be the tool's answer, so neither is stored or paired. Between
            # them they answered the held one's context and the next one waiting (or the
            # tool's, if its context was never seen).
            if asked:
                asked.popleft()
            elif self._pending:
                self._pending.pop(0)
            self._bound = None
            await self._settle(False)
            return
        if asked:
            self._bound = asked.popleft()
        elif self._pending:
            self._bound = ("tool",) + self._pending.pop(0)  # the answer after the tool's result
        else:
            self._bound = None
        self._held = bool(
            self._bound and self._bound[0] == "caller"
            and (self._pending or any(e and e[0] == "tool" for e in asked))
        )

    async def _settle(self, answered: bool) -> None:
        """Record a held response as its caller's answer, or drop it."""
        deferred, self._deferred = self._deferred, None
        if deferred is None:
            return
        if answered:
            await self._record(*deferred)
            return
        await self._audio.settle(deferred[1], False)
        # Reported with no question: it is never paired with a caller turn.
        await self._report_answer({
            "question": "", "answer": deferred[1], "messages": [], "saved": "not_saved",
            "stored": False, "not_stored": "could not be told apart from a tool's late answer",
        })

    async def _record(self, bound: tuple, answer: str) -> None:
        kind, turn, question, messages = bound
        if not question or (kind == "tool" and turn is None):
            # Only what the caller said is recorded, and only for a turn it belongs to.
            await self._audio.settle(answer, False)
            return
        # Record first, so the report can say what happened to the answer. The system
        # messages the model read (and the LLM service's own instruction, where the
        # adapter knows it) are its instructions: an answer repeating a detail they give
        # about this caller is never shared.
        instructions = "\n".join(p for p in (_instructions(messages),
                                              getattr(self, "_service_instructions", None) or "") if p)
        # Passed only when there are some, so a session written for the earlier signature
        # (a test double, a subclass) keeps working.
        extra = {"instructions": instructions} if instructions else {}
        if turn is None and kind == "caller":
            saved = await asyncio.to_thread(self._session._record_model_turn, question, answer, **extra)
        else:
            saved = await asyncio.to_thread(
                self._session._record_model_turn, question, answer, turn=turn, private=kind == "tool", **extra
            )
        await self._audio.settle(answer, await asyncio.to_thread(self._clip_allowed, saved))
        stored = saved in ("saved", "template")
        await self._report_answer({
            "question": question, "answer": answer, "messages": messages, "saved": saved,
            "stored": stored, "not_stored": "" if stored else (getattr(saved, "why", "") or str(saved)),
        })

    def _clip_allowed(self, saved: str) -> bool:
        """Whether the spoken audio of a new answer may be kept, given what happened to
        its text. Only an answer saved word for word: a template is saved with this
        caller's values taken out, but its audio still says them. And not while the
        server's decision engine holds answers until it vouches for them: the text is
        not shared yet and may be removed, so the clip is made when it is first served."""
        if saved != "saved":
            return False
        agent = self._session.agent
        return not (agent.decides() and agent._holds)


__all__ = ["AudioClips", "AnswerPairing", "TTS_TOOL"]
