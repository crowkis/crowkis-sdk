"""TurnPairing: which turn of a call an answer belongs to."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from ..turns.checked import Checked
from ..turns.outcome import Outcome
from ..turns.verdict import Verdict

if TYPE_CHECKING:
    from ..turns.answered import VoiceAnswered

INTERRUPTED = Verdict("Interrupted", "the caller moved on before this answer was complete", outcome=Outcome.INTERRUPTED)


class TurnPairing:
    """Pairs each model answer with the turn it answers, so an answer to a turn the caller talked
    over, or to one before the latest, is never saved or lands on later words.

    Every decided turn gets a number (``begin``); the open turn can be cancelled (barge-in); a
    turn's answer may be shared only if the latest decision for that same turn said so
    (``offer``) and nothing moved on before it is recorded (``settle``). One re-entrant lock
    (``lock``, which the session also records under) guards numbering, offering, cancelling and
    settling; ``start`` and the ``is_open`` / ``cancelled`` flags are set by the session's own turn
    steps, as before.

    Also TurnCore's Pairing for a voice call (``session``, read live for its transcript): ``open()``
    numbers a turn and opens it where it starts in the transcript (a barge-in trims back to there);
    ``settle()`` makes an answer to a turn the caller moved on from ``Interrupted``, and a paired
    answer carries whether decide() let it be shared."""

    NOTHING_SHARED: Tuple[int, bool] = (0, False)

    def __init__(self, session: Optional[object] = None) -> None:
        self._session = session
        self.lock = threading.RLock()
        self.turn = 0
        self.is_open = False
        self.cancelled = False
        self.mark = 0
        self._shareable: Tuple[int, bool] = self.NOTHING_SHARED

    def begin(self) -> int:
        """Number the next decided turn."""
        with self.lock:
            self.turn += 1
            return self.turn

    def open(self) -> int:
        turn = self.begin()
        self.start(len(self._session.transcript))
        return turn

    def settle(self, answered: "VoiceAnswered") -> Checked:
        settled = self.settle_turn(answered.turn)
        if settled is None:
            return Checked(answered, INTERRUPTED)
        _, shareable = settled
        return Checked(answered.paired(shareable))

    def start(self, mark: int) -> None:
        """The turn being decided is open; ``mark`` is where it starts in the transcript."""
        self.mark = mark
        self.is_open = True
        self.cancelled = False

    def offer(self, turn: int, cacheable: bool) -> None:
        """What decide() said about sharing ``turn``'s answer; a newer turn's word is never overwritten."""
        with self.lock:
            if turn == self.turn:
                self._shareable = (turn, cacheable)

    def cancel(self, trim: Callable[[int], None]) -> bool:
        """Barge-in: the open turn is closed and ``trim(mark)`` drops it from the transcript, under
        the lock, so a save finishing on another thread never adds to it meanwhile."""
        with self.lock:
            if not self.is_open:
                return False
            self.is_open = False
            self.cancelled = True
            trim(self.mark)
            return True

    def moved_on(self, turn: int) -> bool:
        """The caller talked over ``turn``, or a newer turn has been decided."""
        with self.lock:
            return self.cancelled or turn != self.turn

    def settle_turn(self, turn: Optional[int]) -> Optional[Tuple[int, bool]]:
        """The answer to ``turn`` (None: the latest) arrived. None when the caller moved on;
        otherwise (that turn, whether decide() let its answer be shared). Closes the turn."""
        with self.lock:
            expected = self.turn if turn is None else turn
            if self.cancelled or expected != self.turn:
                return None
            self.is_open = False
            shareable, self._shareable = self._shareable, self.NOTHING_SHARED
        return expected, shareable[1] and shareable[0] == expected

    def drop_shareable(self) -> bool:
        """A turn kept to the call without a decision (a realtime model's): forget what decide()
        offered. True when it had offered to share."""
        with self.lock:
            offered = self._shareable[1]
            self._shareable = self.NOTHING_SHARED
            return offered
