"""TurnPairing: which turn of a call an answer belongs to."""

from __future__ import annotations

import threading
from typing import Callable, Optional, Tuple


class TurnPairing:
    """Pairs each model answer with the turn it answers, so an answer to a turn the caller talked
    over, or to one before the latest, is never saved or lands on later words.

    Every decided turn gets a number (``begin``); the open turn can be cancelled (barge-in); a
    turn's answer may be shared only if the latest decision for that same turn said so
    (``offer``) and nothing moved on before it is recorded (``settle``). One re-entrant lock
    (``lock``, which the session also records under) guards numbering, offering, cancelling and
    settling; ``start`` and the ``open`` / ``cancelled`` flags are set by the session's own turn
    steps, as before."""

    NOTHING_SHARED: Tuple[int, bool] = (0, False)

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.turn = 0
        self.open = False
        self.cancelled = False
        self.mark = 0
        self._shareable: Tuple[int, bool] = self.NOTHING_SHARED

    def begin(self) -> int:
        """Number the next decided turn."""
        with self.lock:
            self.turn += 1
            return self.turn

    def start(self, mark: int) -> None:
        """The turn being decided is open; ``mark`` is where it starts in the transcript."""
        self.mark = mark
        self.open = True
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
            if not self.open:
                return False
            self.open = False
            self.cancelled = True
            trim(self.mark)
            return True

    def moved_on(self, turn: int) -> bool:
        """The caller talked over ``turn``, or a newer turn has been decided."""
        with self.lock:
            return self.cancelled or turn != self.turn

    def settle(self, turn: Optional[int]) -> Optional[Tuple[int, bool]]:
        """The answer to ``turn`` (None: the latest) arrived. None when the caller moved on;
        otherwise (that turn, whether decide() let its answer be shared). Closes the turn."""
        with self.lock:
            expected = self.turn if turn is None else turn
            if self.cancelled or expected != self.turn:
                return None
            self.open = False
            shareable, self._shareable = self._shareable, self.NOTHING_SHARED
        return expected, shareable[1] and shareable[0] == expected

    def drop_shareable(self) -> bool:
        """A turn kept to the call without a decision (a realtime model's): forget what decide()
        offered. True when it had offered to share."""
        with self.lock:
            offered = self._shareable[1]
            self._shareable = self.NOTHING_SHARED
            return offered
