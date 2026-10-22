"""WriteWorkers: the threads cache writes finish on after a turn stopped waiting for them."""

from __future__ import annotations

import concurrent.futures
import queue
import threading
from typing import Any, Callable, Set


class WriteWorkers:
    """A fixed number of daemon threads, started on the first write, so a write to a hung server
    never holds up the program's exit (a cache write lost at exit costs a later hit). ``pending``
    holds the writes a turn handed over and is no longer waiting for."""

    def __init__(self, threads: int, name: str = "crowkis-voice-write") -> None:
        self._threads = threads
        self._name = name
        self._queue: "queue.Queue" = queue.Queue()
        self._started = False
        self._start_lock = threading.Lock()
        self.pending: Set[concurrent.futures.Future] = set()
        self.pending_lock = threading.Lock()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> concurrent.futures.Future:
        """Run ``fn`` on a worker; its future gets the result or the error."""
        self._start()
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._queue.put((future, fn, args, kwargs))
        return future

    def hand_over(self, future: concurrent.futures.Future) -> None:
        """A write that keeps running after its turn; it leaves ``pending`` when it ends."""
        with self.pending_lock:
            self.pending.add(future)
        future.add_done_callback(self._finished)

    def wait(self) -> None:
        """For tests: every handed-over write, and everything else on the workers, has finished."""
        with self.pending_lock:
            pending = list(self.pending)
        concurrent.futures.wait(pending)
        if self._started:
            self._queue.join()

    def _finished(self, future: concurrent.futures.Future) -> None:
        with self.pending_lock:
            self.pending.discard(future)

    def _start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            for number in range(self._threads):
                threading.Thread(target=self._work, name=f"{self._name}-{number}", daemon=True).start()
            self._started = True

    def _work(self) -> None:
        while True:
            future, fn, args, kwargs = self._queue.get()
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except BaseException as err:  # noqa: BLE001 - handed to the waiting turn
                        future.set_exception(err)
            finally:
                self._queue.task_done()
