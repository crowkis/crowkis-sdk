"""The one place a Crowkis failure is turned into 'carry on without it'."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Awaitable, Optional, TypeVar

Result = TypeVar("Result")

_LOG = logging.getLogger("crowkis.bolna")


class FailOpenBoundary:
    """Runs a Crowkis step and swallows its failure, so a live call never breaks because of
    Crowkis. Each failure is counted per concern (``failures``) and logged by type only:
    never the caller's words."""

    def __init__(self, logger: logging.Logger = _LOG) -> None:
        self._logger = logger
        self.failures: Counter = Counter()

    async def attempt(self, concern: str, step: Awaitable[Result]) -> Optional[Result]:
        """The step's result, or None when it failed."""
        try:
            return await step
        except Exception as error:  # noqa: BLE001 - this is the boundary
            self.failures[concern] += 1
            self._logger.warning("crowkis %s failed, the call goes on without it (%s)", concern,
                                 type(error).__name__)
            return None
