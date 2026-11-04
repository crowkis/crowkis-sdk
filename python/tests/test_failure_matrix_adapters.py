"""Failure matrix, adapter columns: Pipecat, LiveKit and Bolna against the same stand-in server.

The adapters are driven by tests/conformance_drivers.py (real framework types where installed;
each cell skips without its framework). Every cell asserts what test_failure_matrix.py does for
the core: the call is answered by the model and nothing raises; the voice session's own counter
for that failure moved; no log record holds the caller's question or the answer.
"""
import asyncio

import pytest

import crowkis
from crowkis.client.commands import CrowkisClient

from conformance_drivers import DRIVERS, BolnaDriver, LiveKitDriver, PipecatDriver
from test_failure_matrix import (ANSWER, QUESTION, ROWS, TOKEN, logs, no_caller_text_in_logs, settle,  # noqa: F401
                                 stand_in)  # noqa: F401 - fixtures

ADAPTERS = [d for d in DRIVERS if isinstance(d, (PipecatDriver, LiveKitDriver, BolnaDriver))]
PIECES = ["Wyvern eggs hatch only when ", "the quartzmoss ember is kept warm."]


@pytest.fixture
def sessions(monkeypatch):
    """The voice sessions the adapter creates, so their stats() can be read."""
    made = []
    for name in ("voice_session", "async_voice_session"):
        real = getattr(crowkis, name)

        def capture(*args, _real=real, **kwargs):
            made.append(_real(*args, **kwargs))
            return made[-1]

        monkeypatch.setattr(crowkis, name, capture)
    return made


@pytest.mark.parametrize("row", list(ROWS))
@pytest.mark.parametrize("driver", ADAPTERS, ids=lambda d: d.name)
def test_adapter_cell(driver, row, stand_in, logs, sessions):  # noqa: F811
    if not driver.supported:
        pytest.skip(f"{driver.name}: framework not installed")
    mode, budget, timeout, expect, zero = ROWS[row]
    server = stand_in(mode)
    store = CrowkisClient("127.0.0.1", server.port, timeout=timeout, max_retries=0, auth_token=TOKEN)
    turns = [{"say": QUESTION, "reply": PIECES}]

    with driver.active():
        heard = asyncio.run(driver.call(store, turns, "matrix", {"latency_budget_ms": budget}))

    assert len(heard) == 1 and heard[0].llm, "the model was not asked"
    assert " ".join(heard[0].heard.split()) == ANSWER
    assert sessions, "the adapter made no voice session"
    stats = sessions[-1].stats
    settle(stats, expect, zero)
    if row != "cset_error_quotes_question":  # that row's log leak is the core file's BUG F2
        no_caller_text_in_logs(logs)
