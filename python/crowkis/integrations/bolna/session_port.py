"""One awaitable surface over the two kinds of Crowkis voice session."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Optional

from ...voice import TurnDecision


class SessionPort:
    """Adapter: lets the LLM wrapper use an AsyncVoiceSession or a VoiceSession alike.

    A session whose ``decide`` is a coroutine function is awaited on the event loop (it
    moves its own waits off the loop); a plain VoiceSession runs in a worker thread so a
    slow lookup never stalls the other calls sharing the loop. Quick calls (``cancel``,
    ``heard``) are made directly."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._is_async = inspect.iscoroutinefunction(session.decide)

    async def decide(self, caller_said: str) -> TurnDecision:
        """The session's ruling on one caller turn."""
        if self._is_async:
            return await self._session.decide(caller_said)
        return await asyncio.to_thread(self._session.decide, caller_said)

    async def record(self, decision: TurnDecision, answer: str, system: Optional[str]) -> None:
        """Hand a finished model answer to the session; ``system`` is the prompt the model read."""
        if self._is_async:
            await self._session.record(decision, answer, system=system)
        else:
            await asyncio.to_thread(self._session.record, decision, answer, system=system)

    async def close(self) -> None:
        """Close the session's agent (and the client it opened)."""
        if self._is_async:
            await self._session.close()
        else:
            await asyncio.to_thread(self._session.close)

    def heard(self, caller_said: str) -> None:
        """A caller turn this session never decided (see VoiceSession._heard)."""
        self._session._heard(caller_said)

    def cancel(self) -> None:
        """The caller talked over the current turn: its answer is never saved."""
        self._session.cancel()
