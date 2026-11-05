"""Failure matrix: every server failure x every core entry point, against a real TCP socket.

A tiny RESP stand-in on 127.0.0.1 is told to hang, answer slowly, refuse CSET or refuse AUTH
(and a closed port is "down"), so the client's real socket code runs. Each cell asserts:
no exception reaches the call; a defined outcome (the model answered, the save is "not stored"
with a reason); the specific counter that failure must move; and that no log record carries
the caller's question or the answer, only an error type.
"""
import asyncio
import logging
import socket
import threading
import time

import pytest

import crowkis
from crowkis.channels.realtime import RealtimeAdapter, RealtimeGate
from crowkis.client.commands import CrowkisClient

# Distinctive phrases so the log check is real.
QUESTION = "how do wyvern eggs hatch under a gloomy moonlit sky"
ANSWER = "Wyvern eggs hatch only when the quartzmoss ember is kept warm."
TOKEN = "matrix-token"
DELAY_S = 0.25  # the "slow" row: after the latency budget, before the timeout
SETTLE_S = 4.0


class RespStandIn:
    """A RESP server that misses every CGET and says OK to everything else, until told otherwise."""

    def __init__(self, mode):
        self.mode = mode
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(64)
        self._listener.settimeout(0.1)
        self.port = self._listener.getsockname()[1]
        self._conns, self._stop = [], threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()[0]
            except OSError:
                continue
            self._conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        reader = conn.makefile("rb")
        try:
            while True:
                head = reader.readline()
                if not head:
                    return
                args = []
                for _ in range(int(head[1:])):
                    size = int(reader.readline()[1:])
                    args.append(reader.read(size))
                    reader.read(2)
                conn.sendall(self._reply(args))
        except (OSError, ValueError):
            pass

    def _reply(self, args):
        command = args[0].upper()
        if self.mode == "hang":
            threading.Event().wait()  # accepted, never answered
        if command == b"AUTH":
            return b"-WRONGPASS invalid username-password pair\r\n" if self.mode == "wrong_token" else b"+OK\r\n"
        if command == b"HELLO":
            return b"+OK\r\n"
        if self.mode == "slow":
            time.sleep(DELAY_S)
        if command == b"CSET" and self.mode == "cset_refused":
            return b"-ERR CSET rejected by security pipeline\r\n"
        if command == b"CSET" and self.mode == "cset_echo":
            # A server whose error quotes the query it refused.
            return b"-ERR cannot store " + args[1] + b"\r\n"
        return b"+OK\r\n" if command == b"CSET" else b"$-1\r\n"

    def close(self):
        self._stop.set()
        for conn in self._conns:
            conn.close()
        self._listener.close()


# row -> server mode, lookup budget (ms), client timeout (s), counters that must reach a value,
# counters that must stay 0. A closed port is "down"; on Windows a refused connect takes the
# connect timeout, so its budget is generous and the counter is the lookup error, not "over budget".
ROWS = {
    "down": ("down", 1000, 0.15,
             {"cache_unavailable": 1, "failed_writes": 1}, ("missed_latency_budget", "slow_writes")),
    "hung": ("hang", 60, 0.3,
             {"missed_latency_budget": 1, "slow_writes": 1, "failed_writes": 1}, ("cache_unavailable",)),
    "slow": ("slow", 60, 1.0,
             {"missed_latency_budget": 1, "slow_writes": 1}, ("failed_writes", "cache_unavailable")),
    "cset_refused": ("cset_refused", 500, 0.5,
                     {"failed_writes": 1}, ("missed_latency_budget", "cache_unavailable", "slow_writes")),
    "wrong_token": ("wrong_token", 500, 0.5,
                    {"cache_unavailable": 1, "failed_writes": 1}, ("missed_latency_budget", "slow_writes")),
    "cset_error_quotes_question": ("cset_echo", 500, 0.5,
                                   {"failed_writes": 1}, ("missed_latency_budget", "cache_unavailable")),
}

# The error class names the SDK may log for these failures.
ERROR_TYPES = ("CrowkisError", "TimeoutError", "ConnectionRefusedError", "OSError")  # class names: a bare word like "timeout" could be a message


def llm(messages):
    return ANSWER


@pytest.fixture
def stand_in():
    made = []

    def start(mode):
        server = RespStandIn(mode)
        if mode == "down":
            server.close()  # the port is now closed: connection refused
        made.append(server)
        return server

    yield start
    for server in made:
        server.close()


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def no_caller_text_in_logs(caplog):
    for record in caplog.records:
        text = record.getMessage() + str(record.args) + str(record.exc_info)
        assert QUESTION not in text and ANSWER not in text, f"caller text in a log: {text}"
        assert "wyvern" not in text.lower() and "quartzmoss" not in text.lower(), f"caller text in a log: {text}"


def logged_an_error_type(caplog):
    return any(name in record.getMessage() for record in caplog.records for name in ERROR_TYPES)


def settle(read, expect, zero=()):
    """The counters a late write moves arrive after the turn: wait until each reaches its value."""
    deadline = time.monotonic() + SETTLE_S
    while time.monotonic() < deadline:
        counts = read()
        if all(counts.get(name, 0) >= value for name, value in expect.items()):
            break
        time.sleep(0.02)
    counts = read()
    for name, value in expect.items():
        assert counts.get(name, 0) == value, f"{name}: want {value}, stats {counts}"
    for name in zero:
        assert counts.get(name, 0) == 0, f"{name} moved: {counts}"


def session_for(row, stand_in, **options):
    mode, budget, timeout, _, _ = ROWS[row]
    server = stand_in(mode)
    return crowkis.voice_session(host="127.0.0.1", port=server.port, timeout=timeout, latency_budget_ms=budget,
                                 auth_token=TOKEN, **options)


def assert_not_stored(decision):
    assert decision.action == "infer" and decision.text == ANSWER
    assert decision.stored is False
    assert isinstance(decision.not_stored, str) and decision.not_stored


# Rows whose failure is logged by the SDK, so the log must name the error type. A slow server
# that answers in time fails nothing, so nothing is logged.
LOGS_A_TYPE = {"down", "hung", "cset_refused", "wrong_token", "cset_error_quotes_question"}
QUOTES_QUESTION = "cset_error_quotes_question"


def check_voice_cell(row, session, decision, logs):
    _, _, _, expect, zero = ROWS[row]
    assert_not_stored(decision)
    settle(session.stats, expect, zero)
    no_caller_text_in_logs(logs)
    if row in LOGS_A_TYPE:
        assert logged_an_error_type(logs), [r.getMessage() for r in logs.records]


ALL_ROWS = list(ROWS)


@pytest.mark.parametrize("row", ALL_ROWS)
def test_voice_answer(row, stand_in, logs):
    session = session_for(row, stand_in)
    check_voice_cell(row, session, session.answer(QUESTION, llm), logs)


@pytest.mark.parametrize("row", ALL_ROWS)
def test_voice_decide_then_record(row, stand_in, logs):
    session = session_for(row, stand_in)
    decision = session.decide(QUESTION)
    assert decision.action == "infer" and decision.needs_model
    check_voice_cell(row, session, session.record(decision, ANSWER), logs)


@pytest.mark.parametrize("row", ALL_ROWS)
def test_voice_respond_stream(row, stand_in, logs):
    session = session_for(row, stand_in)
    response = session.respond(QUESTION, lambda messages: iter(["Wyvern eggs hatch only when ",
                                                                "the quartzmoss ember is kept warm."]))
    assert "".join(response) == ANSWER
    check_voice_cell(row, session, response.decision, logs)


@pytest.mark.parametrize("row", ALL_ROWS)
def test_async_voice_answer(row, stand_in, logs):
    mode, budget, timeout, _, _ = ROWS[row]
    server = stand_in(mode)
    session = crowkis.async_voice_session(host="127.0.0.1", port=server.port, timeout=timeout,
                                          latency_budget_ms=budget, auth_token=TOKEN)
    decision = asyncio.run(session.answer(QUESTION, llm))
    check_voice_cell(row, session, decision, logs)


@pytest.mark.parametrize("row", ["down", "hung", "slow", "wrong_token"])
def test_realtime_gate(row, stand_in, logs):
    # The gate only decides: on any failure the provider is asked to answer (a respond event).
    session = session_for(row, stand_in)
    adapter = RealtimeAdapter(transcript_event="t.done", transcript_field="transcript",
                              inject_event="item.add", respond_event="respond.now")
    gate = RealtimeGate(session, adapter)
    events = gate.handle({"type": "t.done", "transcript": QUESTION})
    assert len(events) == 1 and events[0].get("type") == "respond.now", events
    assert gate.stats()["forwarded"] == 1 and gate.stats()["served"] == 0
    _, _, _, expect, zero = ROWS[row]
    lookup = {k: v for k, v in expect.items() if k in ("cache_unavailable", "missed_latency_budget")}
    settle(session.stats, lookup, [z for z in zero if z in ("cache_unavailable", "missed_latency_budget")])
    no_caller_text_in_logs(logs)


def test_server_error_quoting_the_question_stays_out_of_logs(stand_in, logs):
    session = session_for(QUOTES_QUESTION, stand_in)
    session.answer(QUESTION, llm)
    no_caller_text_in_logs(logs)


def test_hung_auth_reply_fails_at_the_read_timeout_and_pending_writes_drain(stand_in):
    from crowkis.channels.voice_session import _PENDING_WRITES
    server = stand_in("hang")
    client = CrowkisClient(host="127.0.0.1", port=server.port, timeout=0.3, auth_token=TOKEN, max_retries=0)
    started = time.monotonic()
    with pytest.raises(Exception):
        client.cget("q")
    assert time.monotonic() - started < 3.0
    session = session_for("hung", stand_in)
    session.answer(QUESTION, llm)
    settle(session.stats, {"failed_writes": 1})
    deadline = time.monotonic() + SETTLE_S
    while _PENDING_WRITES and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _PENDING_WRITES
