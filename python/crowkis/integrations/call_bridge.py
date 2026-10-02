"""CallBridge: the voice-pipeline logic for CallSession, independent of any framework
(turn understanding v2.2, part 5).

Pipecat (``crowkis.integrations.pipecat_call``) and any other pipeline call into this:

    on_context(messages, tools)  caller finished a turn -> play cached audio / speak text / call the model
    on_answer(text)              the model's full answer -> save if allowed
    on_tts_audio(pcm)            TTS audio for the answer being spoken
    on_bot_stopped()             the answer finished playing -> store its audio if allowed
    on_interruption()            barge-in -> nothing from this turn is saved

Fixes over the 0.5.2 Pipecat processors:
  - a miss keeps the app's system prompt and tools (only the caller's history is replaced)
  - audio is cached ONLY for shared answers (never personal, urgent, task or agent turns)
  - cached audio played back is never re-recorded into the next clip
  - one clip per whole answer (flushed when the bot stops speaking, not per TTS segment)
  - the audio key includes voice, sample rate and format, so clips are never played wrongly
  - every cache call is bounded and wrapped: a failure means "no cached audio", never silence
"""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..session import FILLER, CallSession, TurnResult
from ..verify import SHARED

TTS_TOOL = "crowkis.tts.v2"
_AUDIO = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="crowkis-audio")


@dataclass
class BridgeDecision:
    action: str                                  # "play_audio" | "speak_text" | "model"
    text: Optional[str] = None
    audio: Optional[bytes] = None
    messages: Optional[List[Dict[str, Any]]] = None   # for "model": exactly what the LLM reads
    tools: Any = None
    result: Optional[TurnResult] = None


@dataclass
class _Clip:
    text: Optional[str] = None
    cacheable: bool = False
    pending: bool = False  # recording a shared answer whose save is not decided yet
    pcm: bytearray = field(default_factory=bytearray)


def _content(message: Dict[str, Any]) -> str:
    """Message content as text, also for list-of-parts content."""
    content = message.get("content", "")
    if isinstance(content, list):
        return " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return str(content or "")


class CallBridge:
    def __init__(self, session: CallSession, *, voice: str, sample_rate: int, audio_format: str = "pcm16",
                 audio_budget_ms: float = 150.0, audio_ttl: Optional[int] = None) -> None:
        if not (voice or "").strip():
            raise ValueError("a voice id is required: cached audio is only reusable for the voice that made it")
        self.session = session
        self.voice = voice.strip()
        self.sample_rate = int(sample_rate)
        self.audio_format = audio_format
        self.audio_budget_ms = audio_budget_ms
        self.audio_ttl = audio_ttl
        self.current: Optional[TurnResult] = None
        self._clip = _Clip()
        self.counts = {"audio_hits": 0, "audio_misses": 0, "audio_errors": 0, "audio_saved": 0, "errors": 0}

    # --- caller turn ------------------------------------------------------------------

    def on_context(self, messages: List[Dict[str, Any]], tools: Any = None) -> BridgeDecision:
        self._clip = _Clip()  # a new turn always starts a clean clip
        if not messages or messages[-1].get("role") != "user":
            # Not something the caller said (e.g. the pipeline's own "please repeat"):
            # the model handles it with the full context and nothing is recorded.
            self.current = None
            return BridgeDecision("model", messages=list(messages or []), tools=tools)
        said = _content(messages[-1])
        try:
            result = self.session.handle(said)
        except Exception:  # noqa: BLE001 - never silence: fall back to the model
            self.counts["errors"] += 1
            self.current = None
            return BridgeDecision("model", messages=list(messages), tools=tools)
        self.current = result

        if not result.needs_model and result.text:
            shareable_audio = result.route in (SHARED, FILLER)
            audio = self._audio_get(result.text) if shareable_audio else None
            if audio:
                return BridgeDecision("play_audio", text=result.text, audio=audio, result=result)
            self._clip = _Clip(text=result.text, cacheable=shareable_audio)
            return BridgeDecision("speak_text", text=result.text, result=result)

        if result.messages is not None:
            # A shared miss: keep the app's instructions and tools, replace only the call history.
            system = [m for m in messages if m.get("role") == "system"]
            # Streaming TTS speaks before the answer is complete: record from the start and
            # decide whether to keep the clip once the save is decided.
            self._clip = _Clip(pending=True)
            return BridgeDecision("model", messages=system + list(result.messages), tools=tools, result=result)
        return BridgeDecision("model", messages=list(messages), tools=tools, result=result)

    # --- model answer -----------------------------------------------------------------

    def on_answer(self, text: str, *, mentions: tuple = (), task: Optional[str] = None) -> str:
        result, self.current = self.current, None
        if result is None:
            return "not_recorded"
        try:
            outcome = self.session.record_answer(result, text, mentions=mentions, task=task)
        except Exception:  # noqa: BLE001 - recording must never end a call
            self.counts["errors"] += 1
            outcome = "refused:error"
        # Audio is reusable only when the text itself was saved for everyone.
        clip = self._clip if self._clip.pending else _Clip()
        clip.pending, clip.text, clip.cacheable = False, text, outcome == "saved"
        if not clip.cacheable:
            clip.pcm = bytearray()
        self._clip = clip
        return outcome

    # --- audio --------------------------------------------------------------------------

    def on_tts_audio(self, pcm: bytes) -> None:
        if self._clip.pending or (self._clip.cacheable and self._clip.text):
            self._clip.pcm += pcm

    def on_bot_stopped(self) -> bool:
        clip, self._clip = self._clip, _Clip()
        if not (clip.cacheable and clip.text and clip.pcm):
            return False
        return self._audio_set(clip.text, bytes(clip.pcm))

    def on_interruption(self) -> None:
        self._clip = _Clip()
        self.current = None
        self.session.cancel()

    def _key(self, text: str) -> str:
        return json.dumps({"voice": self.voice, "text": text, "sample_rate": self.sample_rate,
                           "format": self.audio_format}, sort_keys=True)

    def _client(self):
        return getattr(self.session.agent, "_client", None)

    def _audio_get(self, text: str) -> Optional[bytes]:
        client = self._client()
        if client is None:
            return None
        tenant = getattr(self.session.agent, "tenant", None)
        try:
            raw = _AUDIO.submit(client.ctoolget, TTS_TOOL, self._key(text), tenant=tenant).result(
                timeout=self.audio_budget_ms / 1000.0)
        except Exception:  # noqa: BLE001 - timeout or cache down: just synthesise
            self.counts["audio_errors"] += 1
            return None
        if not raw:
            self.counts["audio_misses"] += 1
            return None
        try:
            audio = base64.b64decode(raw if isinstance(raw, (bytes, str)) else str(raw), validate=True)
        except (ValueError, binascii.Error):
            self.counts["audio_errors"] += 1
            return None
        self.counts["audio_hits"] += 1
        return audio or None

    def _audio_set(self, text: str, pcm: bytes) -> bool:
        client = self._client()
        if client is None:
            return False
        try:
            client.ctoolset(TTS_TOOL, self._key(text), base64.b64encode(pcm).decode("ascii"),
                            ex=self.audio_ttl, tenant=getattr(self.session.agent, "tenant", None))
        except Exception:  # noqa: BLE001
            self.counts["audio_errors"] += 1
            return False
        self.counts["audio_saved"] += 1
        return True


__all__ = ["CallBridge", "BridgeDecision", "TTS_TOOL"]
