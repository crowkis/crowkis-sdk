"""Crowkis in a LiveKit Agents voice agent.

    from livekit.agents import Agent
    from crowkis.integrations.livekit import CrowkisVoice

    class Assistant(CrowkisVoice, Agent):
        def __init__(self):
            super().__init__(instructions="You are Acme's phone assistant.")

Put CrowkisVoice before Agent. Each Agent (one per call) gets its own Crowkis session,
made with crowkis.async_voice_session() (server settings from the environment, live-call
defaults); pass ``crowkis=`` to use your own (an AsyncVoiceSession or VoiceSession), or
set ``crowkis_options`` on the class for async_voice_session()'s options.

llm_node   asks Crowkis first, on a reply to what the caller just said. A cached answer
           is spoken without the LLM; otherwise the LLM answers through LiveKit's own
           llm_node, reading the agent's instructions and only what Crowkis chose (the
           question, or the questions it follows on from; the whole call for a personal
           turn), with its tools. A complete answer is saved when it is safe to share and
           LiveKit has confirmed the reply will be spoken: a reply cancelled while it was
           being written, or a preemptive attempt LiveKit discarded, is never saved (one
           interrupted while being spoken was complete, and is). An answer built from a
           tool's result stays in the call. A reply that is not to a new caller turn
           (generate_reply(instructions=...), on_enter) and a turn whose context carries
           more than the conversation (RAG or CRM messages added in
           on_user_turn_completed, a tool still running) go to the LLM unchanged, with
           the whole context, and are never shared.
tts_node   plays a cached answer's audio without the TTS when Crowkis has it, and keeps
           a new answer's audio once its text was saved word for word. A clip is kept only
           for the run that spoke that answer's text (a say() greeting never lands under
           an answer). The voice id and sample rate come from the session's TTS.

Needs ``livekit-agents`` 1.x.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterable, Optional

from livekit import rtc
from livekit.agents import Agent, llm

try:  # the reply (speech) both nodes of one reply run under
    from livekit.agents.voice.agent_activity import _SpeechHandleContextVar
except ImportError:  # pragma: no cover - a LiveKit without it: one reply at a time
    _SpeechHandleContextVar = None
try:
    from livekit.agents.voice.generation import _RUNNING_PLACEHOLDER_KEY
except ImportError:  # pragma: no cover
    _RUNNING_PLACEHOLDER_KEY = "__lk_running_placeholder__"

from ..voice import VoiceSession
from ..voice_async import AsyncVoiceSession, _on_server_pool, async_voice_session
from ..voice_turns import AudioClips

# A replayed clip is sent in frames of this length.
_FRAME_MS = 20


def _text_of(item: Any) -> str:
    text = getattr(item, "text_content", None)
    return text if isinstance(text, str) else ""


def _last_user(chat_ctx: Any) -> tuple:
    """The last user message's text, and the items after it."""
    items = list(chat_ctx.items)
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "user":
            return _text_of(item), items[index + 1:]
    return None, items


def _earlier_callers(chat_ctx: Any) -> list:
    """What the caller said before the last user message, as text."""
    users = [item for item in chat_ctx.items
             if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "user"]
    return [_text_of(item) for item in users[:-1]]


def _leading_instructions(chat_ctx: Any) -> list:
    """The agent's instructions: the system / developer message LiveKit puts first. Any
    other system message (RAG or CRM data, even right after it) is extra context."""
    items = list(chat_ctx.items)
    first = items[0] if items else None
    if getattr(first, "type", None) == "message" and getattr(first, "role", None) in ("system", "developer"):
        return [first]
    return []


def _is_tool_item(item: Any) -> bool:
    return getattr(item, "type", None) in ("function_call", "function_call_output")


def _is_conversation(item: Any) -> bool:
    """A plain turn of the conversation: something the caller or the agent said."""
    return getattr(item, "type", None) == "message" and getattr(item, "role", None) in ("user", "assistant")


# LiveKit's own bookkeeping in the chat context (an instructions or tools update before
# a call's first turn, an agent handoff, a cache marker): never context for the model.
_BOOKKEEPING = frozenset({"agent_config_update", "agent_handoff", "cache_breakpoint"})


def _extra_context(chat_ctx: Any) -> bool:
    """Whether the context carries more than instructions and conversation for this turn:
    messages or tool items right before the caller's last message (RAG or CRM data an app
    adds in on_user_turn_completed), or a tool still running anywhere."""
    items = list(chat_ctx.items)
    if any(_RUNNING_PLACEHOLDER_KEY in (getattr(i, "extra", None) or {}) for i in items):
        return True
    leading = len(_leading_instructions(chat_ctx))
    last_user = max((n for n, i in enumerate(items)
                     if getattr(i, "type", None) == "message" and getattr(i, "role", None) == "user"), default=-1)
    index = last_user - 1
    while index >= leading and getattr(items[index], "type", None) in _BOOKKEEPING:
        index -= 1
    # The item just before the caller's message (LiveKit's bookkeeping aside) is not conversation.
    return index >= leading and not _is_conversation(items[index])


def _speech() -> Any:
    """The reply (LiveKit SpeechHandle) the current node runs for, if any."""
    if _SpeechHandleContextVar is None:
        return None
    try:
        return _SpeechHandleContextVar.get()
    except LookupError:
        return None


async def _will_be_spoken(handle: Any) -> bool:
    """Whether LiveKit will really play this reply: not interrupted, and scheduled (a
    preemptive attempt waits here until LiveKit keeps or discards it)."""
    if handle is None:
        return True
    if handle.interrupted:
        return False
    if not handle.scheduled:
        await handle.wait_if_not_interrupted([asyncio.ensure_future(handle._wait_for_scheduled())])
    return not handle.interrupted


def _voice_of(tts: Any) -> Optional[str]:
    """The voice a LiveKit TTS plugin speaks with, where it says."""
    for holder in (tts, getattr(tts, "_opts", None)):
        for name in ("voice", "voice_id", "voice_name", "speaker"):
            value = getattr(holder, name, None)
            value = getattr(value, "id", value)  # some plugins keep a Voice object
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


class _Turn:
    """What llm_node decided for the reply in progress, for tts_node."""

    __slots__ = ("decision", "question", "audio", "tool_recorded")

    def __init__(self, decision: Any, question: str, audio: Optional[bytes] = None):
        self.decision = decision
        self.question = question
        self.audio = audio
        self.tool_recorded = False


class CrowkisVoice:
    """Mixin for a LiveKit ``Agent``: ``class Assistant(CrowkisVoice, Agent)``. See the
    module docstring."""

    #: Options for crowkis.async_voice_session() when no ``crowkis=`` is given.
    crowkis_options: Optional[dict] = None

    def __init__(self, *args: Any, crowkis: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if isinstance(crowkis, VoiceSession):
            crowkis = AsyncVoiceSession.wrap(crowkis)
        self._crowkis: Optional[AsyncVoiceSession] = crowkis
        self._crowkis_clips: Optional[AudioClips] = None
        # Per reply (keyed by its LiveKit speech id): what llm_node decided, for its tts_node.
        self._crowkis_turns: dict = {}
        self._crowkis_owns_voice = False

    # -- wiring ---------------------------------------------------------------------

    @property
    def crowkis(self) -> AsyncVoiceSession:
        """This call's Crowkis session (made on first use)."""
        if self._crowkis is None:
            self._crowkis = async_voice_session(**dict(self.crowkis_options or {}))
        return self._crowkis

    def _crowkis_tts(self) -> Any:
        """The TTS the agent speaks with: its own, or the session's."""
        try:
            return self._get_activity_or_raise().tts  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — not started yet (or a test)
            tts = getattr(self, "tts", None)
            return tts if tts is not None and not type(tts).__name__ == "NotGiven" else None

    def _crowkis_clip_cache(self) -> AudioClips:
        session = self.crowkis.session
        if self._crowkis_clips is None:
            clips = AudioClips.__new__(AudioClips)
            clips._init_clips(session, 0)
            self._crowkis_clips = clips
        clips = self._crowkis_clips
        tts = self._crowkis_tts()
        if tts is not None:
            rate = getattr(tts, "sample_rate", None)
            if isinstance(rate, int) and rate > 0:
                clips.sample_rate = rate
            voice = _voice_of(tts)
            if voice and (getattr(session, "_text_only", False) or self._crowkis_owns_voice):
                # The session had no voice: the TTS's keys its audio from now on, and is
                # followed if it changes (update_options, a handoff).
                session.voice, session._text_only, self._crowkis_owns_voice = voice, False, True
        return clips

    def _crowkis_keep(self, key: Any, turn: _Turn) -> None:
        """Remember what was decided for a reply; only the last few replies are kept (a
        tool's follow-up reuses its reply's entry)."""
        self._crowkis_turns.pop(key, None)
        self._crowkis_turns[key] = turn
        while len(self._crowkis_turns) > 8:
            self._crowkis_turns.pop(next(iter(self._crowkis_turns)))

    def _crowkis_instructions(self, chat_ctx: Any) -> str:
        return "\n".join(t for t in (_text_of(item) for item in _leading_instructions(chat_ctx)) if t)

    def _crowkis_model_context(self, chat_ctx: Any, chosen: list) -> Any:
        """The agent's instructions, then only what Crowkis chose for the model to read."""
        items = list(_leading_instructions(chat_ctx))
        items += [llm.ChatMessage(role=m["role"], content=[m["content"]]) for m in chosen]
        return llm.ChatContext(items)

    # -- nodes ----------------------------------------------------------------------

    async def llm_node(self, chat_ctx: Any, tools: list, model_settings: Any):  # type: ignore[override]
        session = self.crowkis
        core = session.session
        handle = _speech()
        key = getattr(handle, "id", None)
        question, after = _last_user(chat_ctx)
        instructions = self._crowkis_instructions(chat_ctx)
        extra = {"instructions": instructions} if instructions else {}
        clips = self._crowkis_clip_cache()

        if question is not None and any(_is_tool_item(item) for item in after):
            # The answer after a tool's result: right for this call only.
            turn = self._crowkis_turns.get(key)
            parts: list = []
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                parts.append(_chunk_text(chunk))
                yield chunk
            answer = "".join(parts).strip()
            if (turn is not None and answer and turn.question == question and not turn.tool_recorded
                    and await _will_be_spoken(handle)):
                turn.tool_recorded = True  # a tool used in several steps is recorded once
                await _on_server_pool(core._record_model_turn, question, answer, turn=turn.decision.turn,
                                      private=True, **extra)
            return

        if question is None or not question.strip() or after:
            # Not a reply to what the caller just said (generate_reply(instructions=...),
            # on_enter): the model answers as LiveKit asked, and nothing is cached.
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                yield chunk
            return

        for said in _earlier_callers(chat_ctx):
            # History the app gave the model: what the caller told the call there counts too.
            core._heard(said)

        if _extra_context(chat_ctx):
            # RAG / CRM messages for this turn, or a tool still running: the model needs the
            # whole context, so the answer is this call's only. Kept in the call's transcript,
            # so later follow-ups are keyed on what was really said.
            parts = []
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                parts.append(_chunk_text(chunk))
                yield chunk
            answer = "".join(parts).strip()
            if answer and await _will_be_spoken(handle):
                await _on_server_pool(core.record_private_turn, question, answer)
            return

        decision = await session.decide(question)
        if not decision.needs_model:
            audio = decision.audio if _pcm_at(core, clips.sample_rate) else None
            if audio is None and decision.audio_shareable:
                audio = await clips.get(decision.text)
            self._crowkis_keep(key, _Turn(decision, question, audio))
            if audio is None and decision.audio_shareable:
                clips.expect(decision.text, shareable=True)  # its audio may be kept this time
            yield decision.text
            if not await _will_be_spoken(handle):
                # A preemptive attempt LiveKit discarded: as if never said.
                self._crowkis_turns.pop(key, None)
                core.cancel()
            return

        self._crowkis_keep(key, _Turn(decision, question))
        messages = chat_ctx if decision.messages is None else self._crowkis_model_context(chat_ctx, decision.messages)
        slot = clips.reserve(None, trusted=True)  # this answer's TTS run, in order
        parts = []
        called_tool = False
        try:
            async for chunk in Agent.default.llm_node(self, messages, tools, model_settings):
                parts.append(_chunk_text(chunk))
                if _chunk_calls_tool(chunk):
                    called_tool = True
                yield chunk
        except BaseException:
            clips.release(slot)  # cancelled while it was written: no run, no clip
            raise
        answer = "".join(parts).strip()
        if not await _will_be_spoken(handle):
            clips.release(slot)  # a preemptive attempt LiveKit discarded: never saved
            self._crowkis_turns.pop(key, None)
            return
        if called_tool or not answer:
            clips.release(slot)  # the answer comes after the tool's result, or there is none
            if not answer and not called_tool:
                await session.record(decision, "")
            return
        slot[0] = answer
        decision._recorded, decision._said = True, None
        outcome = await _on_server_pool(core._record_model_turn, question, answer, turn=decision.turn, **extra)
        decision.stored = outcome in ("saved", "template")
        decision.text = answer
        await clips.settle(answer, await _on_server_pool(_clip_allowed, core, outcome))

    async def tts_node(self, text: AsyncIterable[str], model_settings: Any):  # type: ignore[override]
        handle = _speech()
        key = getattr(handle, "id", None)
        turn = self._crowkis_turns.get(key)
        clips = self._crowkis_clip_cache()
        if turn is not None and turn.audio is not None and not turn.decision.needs_model:
            # This reply is a cached answer whose audio Crowkis has: played without the TTS.
            self._crowkis_turns.pop(key, None)
            async for _ in text:
                pass
            tts = self._crowkis_tts()
            channels = getattr(tts, "num_channels", 1) or 1
            for frame in _frames(turn.audio, clips.sample_rate or 24000, channels):
                yield frame
            return
        spoken: list = []

        async def heard() -> AsyncIterable[str]:
            async for piece in text:
                spoken.append(piece)
                yield piece

        clips.tts_started()
        ended = False
        try:
            async for frame in Agent.default.tts_node(self, heard(), model_settings):
                clips.tts_audio(bytes(frame.data))
                yield frame
            ended = True
        finally:
            if not ended:
                clips.interrupted()  # cut off: no clip, and the order of runs starts again
        clips.tts_text("".join(spoken))  # a clip is kept only under the text this run spoke
        await clips.tts_stopped()


def _pcm_at(core: VoiceSession, rate: int) -> bool:
    """Whether the session's own synthesiser makes 16-bit PCM at the TTS's rate, so its
    audio can be played as LiveKit frames."""
    return bool(rate) and getattr(core, "audio_format", "default") == f"pcm16-{rate}"


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    delta = getattr(chunk, "delta", None)
    content = getattr(delta, "content", None)
    return content if isinstance(content, str) else ""


def _chunk_calls_tool(chunk: Any) -> bool:
    delta = getattr(chunk, "delta", None)
    return bool(getattr(delta, "tool_calls", None))


def _clip_allowed(core: VoiceSession, outcome: str) -> bool:
    """Only an answer saved word for word (a template's audio says this caller's values),
    and not while the server's decision engine holds answers until it vouches for them."""
    if outcome != "saved":
        return False
    agent = core.agent
    return not (agent.decides() and getattr(agent, "_holds", False))


def _frames(pcm: bytes, rate: int, channels: int):
    """A clip as rtc.AudioFrames of _FRAME_MS each (16-bit PCM)."""
    step = max(2 * channels, (rate * _FRAME_MS // 1000) * 2 * channels)
    for start in range(0, len(pcm), step):
        chunk = pcm[start:start + step]
        samples = len(chunk) // (2 * channels)
        if samples:
            yield rtc.AudioFrame(chunk[: samples * 2 * channels], rate, channels, samples)


__all__ = ["CrowkisVoice"]
