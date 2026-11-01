"""QuestionRecords: which questions each shared answer was saved for, kept on the server."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
from typing import Any, Callable, Optional

from ..understanding.word_rules import _QUESTION_KEY, _different_specifics
from .deadline import within

# The newest questions kept per answer.
QUESTIONS_KEPT = 8
# How long a question record lives when the answer has no TTL of its own.
QUESTION_TTL = 30 * 24 * 3600

_LOG = logging.getLogger("crowkis")


def question_key(tenant: Optional[str], answer: str) -> str:
    """Where an answer's questions are kept: by the tenant and a hash of the answer."""
    digest = hashlib.sha256(answer.strip(" \t\r\n").encode("utf-8")).hexdigest()[:32]
    return _QUESTION_KEY.format(tenant=tenant or "default", answer=digest)


def tenant_of(agent: Any) -> Optional[str]:
    return getattr(agent, "tenant", None) or getattr(getattr(agent, "_client", None), "tenant", None)


class QuestionRecords:
    """The questions each shared answer was saved for, kept next to the answer on the server, so a later
    near hit can be checked against them (DifferentQuestion). Best effort on both sides: a record that
    could not be written only means a later hit cannot be checked, and one that cannot be read in time
    means "not a different question", as before the record existed."""

    def __init__(self, agent: Any, *, read_pool: concurrent.futures.Executor,
                 submit_write: Callable[[Callable[[], None]], Any]) -> None:
        self._agent = agent
        self._read_pool = read_pool
        self._submit_write = submit_write

    def keep(self, question: str, answer: str, ttl: Optional[int] = None) -> None:
        """Note, in the background, that ``answer`` was saved for ``question``."""
        client = getattr(self._agent, "_client", None)
        if client is None or not hasattr(client, "set"):
            return
        key, ttl = question_key(tenant_of(self._agent), answer), ttl or QUESTION_TTL

        def keep() -> None:
            try:
                raw = client.get(key)
                kept = json.loads(raw) if raw else []
                kept = [q for q in kept if isinstance(q, str) and q != question][-(QUESTIONS_KEPT - 1):]
                client.set(key, json.dumps(kept + [question], separators=(",", ":"), ensure_ascii=False), ttl=ttl)
            except Exception as err:  # noqa: BLE001 — see the class docstring
                _LOG.debug("crowkis voice: the answer's question was not kept (%s)", type(err).__name__)

        self._submit_write(keep)  # never on the audio-clip queue

    def answers_another_question(self, asked: str, answer: str, wait_ms: Optional[float]) -> bool:
        """Whether every question ``answer`` was saved for asks about something else, read within
        ``wait_ms`` (None: as long as the server takes). Unknown means no."""
        client = getattr(self._agent, "_client", None)
        if client is None or not hasattr(client, "get"):
            return False
        read = lambda: client.get(question_key(tenant_of(self._agent), answer))  # noqa: E731
        try:
            if wait_ms is None:
                raw = read()
            else:
                if wait_ms <= 0:
                    return False
                raw = within(self._read_pool, wait_ms, read)
            questions = json.loads(raw) if raw else []
        except Exception:  # noqa: BLE001 — see the class docstring
            return False
        questions = [q for q in questions if isinstance(q, str)] if isinstance(questions, list) else []
        return bool(questions) and all(_different_specifics(asked, q) for q in questions)
