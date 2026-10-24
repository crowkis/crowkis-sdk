"""What the LLM wrapper and the synthesizer wrapper of one Bolna call tell each other."""

from __future__ import annotations

import collections
import weakref
from dataclasses import dataclass, field
from typing import Any, Awaitable, List, Optional

from ...voice import _words
from .clip_shelf import ClipOutput, ClipShelf
from .fail_open import FailOpenBoundary

AUDIO_CONCERN = "audio"
END_OF_AUDIO = b"\x00"  # what Bolna's synthesizers send to close a stream: not part of the clip
SEQUENCES_REMEMBERED = 4  # one turn speaks at a time; a few cover a barge-in that leaves one behind


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
    a synthesizer output bound: a call with only one of the two has no audio cache."""

    def __init__(self) -> None:
        self.boundary = FailOpenBoundary()
        self._session: Any = None
        self._output: Optional[ClipOutput] = None
        self._output_bound = False
        self._shelf: Optional[ClipShelf] = None
        self._sequences: "collections.OrderedDict[int, SequenceClip]" = collections.OrderedDict()

    def bind_session(self, session: Any, boundary: FailOpenBoundary) -> None:
        """The LLM wrapper's session, and the boundary its failures are counted on."""
        self._session, self.boundary = session, boundary
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
