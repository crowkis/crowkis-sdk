"""CrowkisSynthesizer: cached voice clips in front of one of Bolna's own synthesizers.

Also holds what the call's LLM wrapper and this wrapper tell each other (``CallLinks``,
``ClipPlan``, ``SequenceClip``) and where the clips are kept (``ClipOutput``, ``ClipShelf``)."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import weakref
from collections import Counter
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, AsyncIterator, Awaitable, List, Optional, TypeVar

from bolna.helpers.utils import create_ws_data_packet

from ...voice import _words
from ...voice_turns import AudioClips

AUDIO_CONCERN = "audio"

WIRE_MULAW = "mulaw"
WIRE_PCM = "pcm"
MULAW_SAMPLE_RATE = 8000
PCM_BYTES_PER_SAMPLE = 2  # AudioClips counts a clip's length in 16-bit samples
END_OF_AUDIO = b"\x00"  # what Bolna's synthesizers send to close a stream: not part of the clip
SEQUENCES_REMEMBERED = 4  # one turn speaks at a time; a few cover a barge-in that leaves one behind
_INNER_DONE = object()

Result = TypeVar("Result")

_LOG = logging.getLogger("crowkis.bolna")


class FailOpenBoundary:
    """The one place a Crowkis failure is turned into "carry on without it", for the LLM and
    the synthesizer alike. It lives here because each call's ``ClipPlan`` owns the one boundary
    both wrappers share.

    Runs a Crowkis step and swallows its failure, so a live call never breaks because of
    Crowkis. Each failure is counted per concern (``failures``) and logged by type only:
    never the caller's words."""

    def __init__(self) -> None:
        self.failures: Counter = Counter()

    async def attempt(self, concern: str, step: Awaitable[Result]) -> Optional[Result]:
        """The step's result, or None when it failed."""
        try:
            return await step
        except Exception as error:  # noqa: BLE001 - this is the boundary
            self.failures[concern] += 1
            _LOG.warning("crowkis %s failed, the call goes on without it (%s)", concern, type(error).__name__)
            return None


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
        # A streaming synthesizer and an HTTP one name their packet format apart.
        declare = getattr(synthesizer, "_get_audio_format" if synthesizer.stream else "_get_http_audio_format", None)
        wire_format = declare() if declare is not None else None
        voice = getattr(synthesizer, "voice_id", None) or getattr(synthesizer, "voice", None)
        if wire_format == WIRE_MULAW:
            sample_rate = MULAW_SAMPLE_RATE
        elif wire_format == WIRE_PCM:
            # Bolna's synthesizers keep the rate as ``sample_rate`` or ``sampling_rate``, a number or a string.
            rate = getattr(synthesizer, "sample_rate", None) or getattr(synthesizer, "sampling_rate", None)
            sample_rate = int(rate) if rate else 0
        else:
            return None
        if not voice or not sample_rate:
            return None
        return cls(wire_format, str(voice), sample_rate)


class ClipShelf(AudioClips):
    """The clips of one call's voice: ``get`` reads one, ``store_clip`` keeps a finished one.

    A Bolna call's voice belongs to its synthesizer, so the shelf reads this call's voice and
    format in place of the session's own and takes the rest from the session."""

    def __init__(self, session: Any, output: ClipOutput) -> None:
        voice = SimpleNamespace(voice=output.voice, audio_format=output.audio_format, language=session.language,
                                speed=session.speed, ttl=session.ttl, agent=session.agent)
        # AudioClips counts 2 bytes a sample; halving the byte rate keeps a mu-law clip's seconds right.
        self._init_clips(voice, output.bytes_per_second // PCM_BYTES_PER_SAMPLE)

    async def store_clip(self, text: str, clip: bytes) -> None:
        """Keep the finished audio of an answer the cache shares (written in the background)."""
        self.expect(text, shareable=True)
        self.tts_started()
        self.tts_audio(clip)
        await self.tts_stopped()


@dataclass
class SequenceClip:
    """The audio of one answer (one Bolna ``sequence_id``): what to play, or what to keep.

    ``playing`` is a cached clip to play in place of speaking the text. Otherwise the
    synthesizer speaks, its audio is gathered here, and ``clip()`` hands it over once the
    answer's text is shared (``vouched``) and everything was spoken."""

    text: Optional[str] = None
    vouched: bool = False
    playing: Optional[bytes] = None
    spoken: List[str] = field(default_factory=list)
    audio: bytearray = field(default_factory=bytearray)
    text_complete: bool = False
    audio_complete: bool = False
    spoiled: bool = False

    def hear_text(self, text: Optional[str], last: bool) -> None:
        """A text piece Bolna gave the synthesizer; ``last`` ends the answer."""
        if isinstance(text, str) and text.strip():
            self.spoken.append(text)
        self.text_complete = self.text_complete or last

    def hear_audio(self, audio: bytes, in_declared_format: bool, last: bool) -> None:
        """A packet of the synthesizer's audio; ``last`` ends its stream."""
        if not in_declared_format:
            self.spoiled = True
        elif audio != END_OF_AUDIO:
            self.audio += audio
        self.audio_complete = self.audio_complete or last

    def clip(self) -> Optional[bytes]:
        """The audio to keep, or None while it is not safe to: the text not shared yet, the
        speech not finished, in another format, or saying other words than the answer."""
        if not (self.vouched and self.text and self.text_complete and self.audio_complete and self.audio):
            return None
        if self.spoiled or _words(" ".join(self.spoken)) != _words(self.text):
            return None
        return bytes(self.audio)


class ClipPlan:
    """One call's audio orders. The LLM wrapper says what each sequence is (served with a clip,
    served without one, or a model answer that may be saved) and the synthesizer wrapper plays
    or gathers audio accordingly. A clip is stored once, when its text is known to be shared
    and its audio is complete, whichever happens last. Nothing is kept without a session and
    a synthesizer output bound: a call with only one of the two has no audio cache.

    ``boundary`` is the call's one fail-open boundary: the LLM wrapper and the synthesizer
    wrapper both count their failures on it."""

    def __init__(self) -> None:
        self.boundary = FailOpenBoundary()
        self._session: Any = None
        self._output: Optional[ClipOutput] = None
        self._output_bound = False
        self._shelf: Optional[ClipShelf] = None
        self._sequences: "collections.OrderedDict[int, SequenceClip]" = collections.OrderedDict()

    def bind_session(self, session: Any) -> None:
        """The LLM wrapper's session."""
        self._session = session
        self._open_shelf()

    def bind_output(self, output: Optional[ClipOutput]) -> None:
        """What the synthesizer wrapper's inner synthesizer sends (None: no clip can be kept).

        A second synthesizer for the same call (Bolna's multilingual pool, one voice per
        language) turns the call's clips off: a clip can't be tied to one voice then."""
        if self._output_bound:
            self._output, self._shelf = None, None
            return
        self._output_bound = True
        self._output = output
        self._open_shelf()

    async def fetch(self, text: str) -> Optional[bytes]:
        """The cached clip of an answer, in this call's voice and format; None on a miss or a failure."""
        if self._shelf is None:
            return None
        return await self._guarded(self._shelf.get(text))

    def play(self, sequence_id: Optional[int], text: str, clip: bytes) -> None:
        """This sequence is a served answer whose clip is cached: play it, never speak the text."""
        self._order(sequence_id, SequenceClip(text=text, playing=clip))

    def keep_served(self, sequence_id: Optional[int], text: str) -> None:
        """This sequence is a served answer with no clip yet: it is spoken, then its audio is stored."""
        self._order(sequence_id, SequenceClip(text=text, vouched=True))

    def keep_answer(self, sequence_id: Optional[int]) -> None:
        """This sequence is a model answer that may be saved: gather its audio and wait for the ruling."""
        self._order(sequence_id, SequenceClip())

    async def settle(self, sequence_id: Optional[int], text: str, shareable: bool) -> None:
        """The ruling on a model answer: its audio is stored (shareable) or dropped."""
        sequence = self._sequences.get(sequence_id)
        if sequence is None:
            return
        if not shareable:
            self.drop(sequence_id)
            return
        sequence.text, sequence.vouched = text, True
        await self._store_if_ready(sequence_id)

    def drop(self, sequence_id: Optional[int]) -> None:
        """Forget a sequence: its audio is never stored."""
        self._sequences.pop(sequence_id, None)

    def drop_all(self) -> None:
        """A barge-in: every sequence in flight is cut off."""
        self._sequences.clear()

    @property
    def wire_format(self) -> Optional[str]:
        """What the synthesizer's packets name their format (set once it is bound)."""
        return self._output.wire_format if self._output is not None else None

    def playing(self, sequence_id: Optional[int]) -> Optional[SequenceClip]:
        """The order to play a clip for this sequence in place of its text, if there is one."""
        sequence = self._sequences.get(sequence_id)
        return sequence if sequence is not None and sequence.playing is not None else None

    def hear_text(self, sequence_id: Optional[int], text: Optional[str], last: bool) -> None:
        """The synthesizer was given a piece of this sequence's text."""
        sequence = self._sequences.get(sequence_id)
        if sequence is not None:
            sequence.hear_text(text, last)

    async def hear_audio(self, sequence_id: Optional[int], audio: bytes, wire_format: Optional[str],
                         last: bool) -> None:
        """The synthesizer produced a packet of this sequence's audio; ``last`` ends its stream.
        Never raises: a packet Crowkis cannot read only costs the clip."""
        await self._guarded(self._hear_audio(sequence_id, audio, wire_format, last))

    async def _hear_audio(self, sequence_id: Optional[int], audio: bytes, wire_format: Optional[str],
                          last: bool) -> None:
        sequence = self._sequences.get(sequence_id)
        if sequence is None or sequence.playing is not None:
            return
        sequence.hear_audio(audio, self._output is not None and wire_format == self._output.wire_format, last)
        await self._store_if_ready(sequence_id)

    def _order(self, sequence_id: Optional[int], sequence: SequenceClip) -> None:
        if sequence_id is None or self._shelf is None:
            return
        self._sequences.pop(sequence_id, None)
        self._sequences[sequence_id] = sequence
        while len(self._sequences) > SEQUENCES_REMEMBERED:
            self._sequences.popitem(last=False)

    async def _store_if_ready(self, sequence_id: Optional[int]) -> None:
        sequence = self._sequences.get(sequence_id)
        clip = sequence.clip() if sequence is not None else None
        if clip is None or self._shelf is None:
            return
        self.drop(sequence_id)
        await self._guarded(self._shelf.store_clip(sequence.text, clip))

    def _open_shelf(self) -> None:
        if self._session is not None and self._output is not None:
            self._shelf = ClipShelf(self._session, self._output)

    async def _guarded(self, step: Awaitable[Any]) -> Optional[Any]:
        return await self.boundary.attempt(AUDIO_CONCERN, step)


class CallLinks:
    """The link between one call's LLM wrapper and synthesizer wrapper: a ClipPlan per task manager.

    ``register_crowkis`` owns one and hands it to both wrapper classes. Bolna builds the two
    separately and gives both the call's task manager, so that is the key. It is weak, so a
    call's plan goes away with the call. A call with no task manager gets a plan of its own
    that nothing else can reach."""

    def __init__(self) -> None:
        self._plans: "weakref.WeakKeyDictionary[Any, ClipPlan]" = weakref.WeakKeyDictionary()

    def plan_for(self, task_manager: Any) -> ClipPlan:
        """The plan of the call that ``task_manager`` runs."""
        if task_manager is None:
            return ClipPlan()
        plan = self._plans.get(task_manager)
        if plan is None:
            plan = self._plans[task_manager] = ClipPlan()
        return plan


class CrowkisSynthesizer:
    """Decorator around a Bolna synthesizer: a served answer whose clip is cached is played
    from the cache, and the audio of an answer the cache shares is kept for the next caller.

    One instance serves one call (Bolna builds one synthesizer per call), and finds the
    LLM wrapper's orders for that call through ``CallLinks``. ``push`` swallows the text of a
    sequence that is to be played from a clip (anything else goes to the wrapped synthesizer
    untouched) and ``generate`` merges the clip's packet with the wrapped synthesizer's own.
    Packets keep Bolna's shape, so its sequence gate, marks and history commit work as for
    any speech. ``handle_interruption`` drops everything in flight; every other attribute and
    method is the wrapped synthesizer's own."""

    def __init__(self, inner: Any, links: CallLinks) -> None:
        self._inner = inner
        self._plan: ClipPlan = links.plan_for(inner.task_manager_instance)
        self._plan.bind_output(ClipOutput.of_synthesizer(inner))
        self._outbox: "asyncio.Queue[Any]" = asyncio.Queue()

    def __getattr__(self, name: str) -> Any:
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    @property
    def failures(self) -> Any:
        """How many times each Crowkis concern failed and was skipped."""
        return self._plan.boundary.failures

    async def push(self, message: dict) -> None:
        """Bolna gives the synthesizer a piece of text: swallowed when its sequence plays a clip."""
        meta_info = message.get("meta_info") or {}
        sequence_id = meta_info.get("sequence_id")
        playing = self._plan.playing(sequence_id)
        if playing is None:
            self._plan.hear_text(sequence_id, message.get("data"), bool(meta_info.get("end_of_llm_stream")))
            await self._inner.push(message)
        elif meta_info.get("end_of_llm_stream"):
            self._plan.drop(sequence_id)
            self._outbox.put_nowait(self._clip_packet(playing, meta_info))

    async def generate(self) -> AsyncIterator[dict]:
        """The wrapped synthesizer's packets, with the clip packets of this call among them."""
        pump = asyncio.create_task(self._pump_inner())
        try:
            while True:
                item = await self._outbox.get()
                if item is _INNER_DONE:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump

    async def handle_interruption(self) -> None:
        """Barge-in: audio collected so far and clips not yet played are dropped."""
        self._plan.drop_all()
        await self._inner.handle_interruption()

    def _clip_packet(self, playing: SequenceClip, meta_info: dict) -> dict:
        """A cached clip as one packet of Bolna's shape, stamped as its own synthesizer would."""
        meta = dict(meta_info)
        self._inner._stamp_first_chunk(meta)
        self._inner._stamp_end_of_stream(meta)
        meta["format"] = self._plan.wire_format
        meta["text"] = playing.text
        meta["text_synthesized"] = f"{playing.text} "
        self._inner._stamp_mark_id(meta)
        return create_ws_data_packet(playing.playing, meta)

    async def _pump_inner(self) -> None:
        try:
            async for packet in self._inner.generate():
                await self._observe(packet)
                self._outbox.put_nowait(packet)
        except Exception as error:  # noqa: BLE001 - handed to generate(), which raises it to Bolna
            self._outbox.put_nowait(error)
        else:
            self._outbox.put_nowait(_INNER_DONE)

    async def _observe(self, packet: dict) -> None:
        meta_info = packet.get("meta_info") or {}
        await self._plan.hear_audio(meta_info.get("sequence_id"), packet.get("data"), meta_info.get("format"),
                                    bool(meta_info.get("end_of_synthesizer_stream")))
