"""VoicePairing: which turn of a voice call an answer belongs to, as TurnCore's Pairing."""

from __future__ import annotations

from ..runtime.turn_pairing import TurnPairing
from .answered import VoiceAnswered
from .checked import Checked
from .turn_host import TurnHost
from .verdict import Verdict

INTERRUPTED = Verdict("Interrupted", "the caller moved on before this answer was complete", outcome="interrupted")


class VoicePairing:
    """Adapter: a call's TurnPairing as TurnCore's Pairing. A turn opens where it starts in the
    transcript (a barge-in trims back to there); an answer to a turn the caller moved on from is
    ``Interrupted``; a paired answer carries whether decide() let it be shared."""

    def __init__(self, pairing: TurnPairing, host: TurnHost) -> None:
        self._pairing = pairing
        self._host = host

    def open(self) -> None:
        self._pairing.start(len(self._host.transcript))

    def settle(self, answered: VoiceAnswered) -> Checked:
        settled = self._pairing.settle(answered.turn)
        if settled is None:
            return Checked(answered, INTERRUPTED)
        _, shareable = settled
        return Checked(answered.paired(shareable))
