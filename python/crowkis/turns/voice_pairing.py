"""VoicePairing: which turn of a voice call an answer belongs to, as TurnCore's Pairing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from ..runtime.turn_pairing import TurnPairing
from .answered import VoiceAnswered
from .checked import Checked
from .outcome import Outcome
from .verdict import Verdict

if TYPE_CHECKING:
    from ..channels.voice_session import VoiceSession

INTERRUPTED = Verdict("Interrupted", "the caller moved on before this answer was complete", outcome=Outcome.INTERRUPTED)


class VoicePairing:
    """Adapter: a call's TurnPairing as TurnCore's Pairing. Every decided turn gets the next number
    and opens where it starts in the transcript (a barge-in trims back to there); an answer to a turn
    the caller moved on from is ``Interrupted``; a paired answer carries whether decide() let it be
    shared."""

    def __init__(self, pairing: TurnPairing, session: VoiceSession) -> None:
        self._pairing = pairing
        self._session = session

    def open(self) -> int:
        turn = self._pairing.begin()
        self._pairing.start(len(self._session.transcript))
        return turn

    def settle(self, answered: VoiceAnswered) -> Checked:
        settled = self._pairing.settle(answered.turn)
        if settled is None:
            return Checked(answered, INTERRUPTED)
        _, shareable = settled
        return Checked(answered.paired(shareable))
