"""Where a call's voice clips are kept: the shared audio cache, in this call's voice and format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ...voice_turns import AudioClips

WIRE_MULAW = "mulaw"
WIRE_PCM = "pcm"
MULAW_SAMPLE_RATE = 8000
PCM_BYTES_PER_SAMPLE = 2  # AudioClips counts a clip's length in 16-bit samples


@dataclass(frozen=True)
class ClipOutput:
    """What one call's synthesizer sends to the caller: the voice and the audio format.

    ``wire_format`` is what Bolna names it in a packet's ``meta_info["format"]``. A clip is
    reused only for the same voice and the same format and rate, as ``Agent.speak()`` does."""

    wire_format: str
    voice: str
    sample_rate: int

    @property
    def audio_format(self) -> str:
        """The format label in a clip's cache key."""
        if self.wire_format == WIRE_MULAW:
            return f"{WIRE_MULAW}-{self.sample_rate}"
        return f"pcm16-{self.sample_rate}"

    @property
    def bytes_per_second(self) -> int:
        """How many bytes of audio make a second of speech."""
        return self.sample_rate * (1 if self.wire_format == WIRE_MULAW else PCM_BYTES_PER_SAMPLE)

    @classmethod
    def of_synthesizer(cls, synthesizer: Any) -> Optional["ClipOutput"]:
        """The output of a Bolna synthesizer, or None when no clip can be kept for it: a format
        that is not raw mu-law or PCM (a WAV is a file per piece), or no voice or rate to key on."""
        wire_format = _declared_format(synthesizer)
        voice = getattr(synthesizer, "voice_id", None) or getattr(synthesizer, "voice", None)
        if wire_format == WIRE_MULAW:
            sample_rate = MULAW_SAMPLE_RATE
        elif wire_format == WIRE_PCM:
            sample_rate = _sample_rate(synthesizer)
        else:
            return None
        if not voice or not sample_rate:
            return None
        return cls(wire_format, str(voice), sample_rate)


def _declared_format(synthesizer: Any) -> Optional[str]:
    """The format a synthesizer says its packets carry (a streaming one and an HTTP one name it apart)."""
    name = "_get_audio_format" if synthesizer.stream else "_get_http_audio_format"
    declare = getattr(synthesizer, name, None)
    return declare() if declare is not None else None


def _sample_rate(synthesizer: Any) -> int:
    """Bolna's synthesizers keep the rate as ``sample_rate`` or ``sampling_rate``, a number or a string."""
    rate = getattr(synthesizer, "sample_rate", None) or getattr(synthesizer, "sampling_rate", None)
    return int(rate) if rate else 0


class CallVoice:
    """Adapter: what ``AudioClips`` reads of a session, with this call's voice and format in
    place of the session's own (a Bolna call's voice belongs to its synthesizer)."""

    def __init__(self, session: Any, output: ClipOutput) -> None:
        self.voice = output.voice
        self.audio_format = output.audio_format
        self.language = session.language
        self.speed = session.speed
        self.ttl = session.ttl
        self.agent = session.agent
        self._text_only = False  # the synthesizer's voice is the key, so a clip can always be keyed


class ClipShelf(AudioClips):
    """The clips of one call's voice: ``get`` reads one, ``store_clip`` keeps a finished one."""

    def __init__(self, session: Any, output: ClipOutput) -> None:
        # AudioClips counts 2 bytes a sample; halving the byte rate keeps a mu-law clip's seconds right.
        self._init_clips(CallVoice(session, output), output.bytes_per_second // PCM_BYTES_PER_SAMPLE)

    async def store_clip(self, text: str, clip: bytes) -> None:
        """Keep the finished audio of an answer the cache shares (written in the background)."""
        self.expect(text, shareable=True)
        self.tts_started()
        self.tts_audio(clip)
        await self.tts_stopped()
