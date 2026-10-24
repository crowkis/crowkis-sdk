"""ChatTurns: a chat's turns (numbering, the turn awaiting an answer, cancelled ones), as TurnCore's Pairing."""

from __future__ import annotations

from typing import Optional, Set

from .answered import ChatAnswered
from .checked import Checked
from .turn_result import TurnResult
from .outcome import Outcome
from .verdict import Verdict

CANCELLED_COUNT = "cancelled"
CANCELLED_VERDICT = Verdict("Cancelled", "the user talked over this turn", (CANCELLED_COUNT,),
                            outcome=Outcome.CANCELLED)
# An older turn finishing after a newer one started: never saved.
STALE_VERDICT = Verdict("Stale", "a newer turn awaits the answer", outcome=Outcome.STALE)


class ChatTurns:
    """Every turn gets the next number (``open``). A turn the agent must answer awaits it
    (``await_answer``); a filler, an urgent script or a tools answer does not, so the turn before
    it still does. An answer is paired only with the turn awaiting one, and never with a cancelled
    turn (a barge-in)."""

    def __init__(self) -> None:
        self.next_turn = 1
        self._awaiting: Optional[TurnResult] = None
        self._cancelled: Set[int] = set()

    def open(self) -> int:
        turn, self.next_turn = self.next_turn, self.next_turn + 1
        return turn

    def await_answer(self, result: TurnResult) -> TurnResult:
        """``result``'s turn is the one the agent's next answer belongs to."""
        self._awaiting = result
        return result

    def settle(self, answered: ChatAnswered) -> Checked:
        turn_id = answered.result.turn_id
        if turn_id in self._cancelled:
            return Checked(answered, CANCELLED_VERDICT)
        if self._awaiting is None or self._awaiting.turn_id != turn_id:
            return Checked(answered, STALE_VERDICT)
        self._awaiting = None
        return Checked(answered)

    def cancel(self) -> bool:
        """Barge-in: the turn awaiting an answer is abandoned and its answer will never be saved."""
        if self._awaiting is None:
            return False
        self._cancelled.add(self._awaiting.turn_id)
        self._awaiting = None
        return True
