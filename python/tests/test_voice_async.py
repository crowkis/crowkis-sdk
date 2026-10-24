"""AsyncVoiceSession: VoiceSession for asyncio, with the same rules.

Every call that waits on the server (decide, answer, record, respond, report_stats)
runs on a dedicated thread pool, so the event loop keeps serving other calls. A sync
model also runs off the loop. cancel(), stats(), injections() and other calls that never
wait stay sync. crowkis.async_voice_session() is voice_session() for asyncio."""

import asyncio
import os
import socket
import threading
import time
import unittest
from unittest import mock

import crowkis
from crowkis import Agent, AsyncVoiceResponse, AsyncVoiceSession, VoiceSession

from test_voice_record import CALLS, _fields
from test_voice_stress_bugs import ANSWER, Store, session_on

_NAMES = ("CROWKIS_HOST", "CROWKIS_PORT", "CROWKIS_AUTH_TOKEN", "CROWKIS_TOKEN", "CROWKIS_TENANT", "CROWKIS_URL")


def _env(**values):
    clean = {k: v for k, v in os.environ.items() if k not in _NAMES}
    clean.update(values)
    return mock.patch.dict(os.environ, clean, clear=True)


def run(coro):
    return asyncio.run(coro)


def async_on(store, **options):
    return AsyncVoiceSession(Agent("caller", client=store), voice="v", **options)


async def _heartbeat(stop, ticks):
    """Counts how often the event loop got to run while something else was waiting."""
    while not stop.is_set():
        ticks.append(time.monotonic())
        await asyncio.sleep(0.01)


async def _words(text):
    if text is None:
        return
    words = text.split(" ")
    for i, word in enumerate(words):
        yield word + (" " if i < len(words) - 1 else "")


class SlowStore(Store):
    """A server whose lookups block the calling thread."""

    def cget_hit(self, query, **kwargs):
        time.sleep(0.2)
        return super().cget_hit(query, **kwargs)


class SameAsSyncTests(unittest.TestCase):
    def test_answer_ends_exactly_as_the_sync_answer_does(self):
        for turns, replies, options in CALLS:
            with self.subTest(turns=turns):
                s_store, a_store = Store(), Store()
                sync, asyn = session_on(s_store, **options), async_on(a_store, **options)

                async def go():
                    out = []
                    for said, reply in zip(turns, replies):
                        async def model(messages, reply=reply):
                            return reply
                        out.append(await asyn.answer(said, model))
                    return out

                a_decisions = run(go())
                s_decisions = [sync.answer(said, lambda m, reply=reply: reply) for said, reply in zip(turns, replies)]
                self.assertEqual(a_store.writes, s_store.writes)
                self.assertEqual(asyn.transcript, sync.transcript)
                self.assertEqual(asyn.stats(), sync.stats())
                self.assertEqual([_fields(d) for d in a_decisions], [_fields(d) for d in s_decisions])

    def test_respond_ends_exactly_as_the_sync_answer_does(self):
        for turns, replies, options in CALLS:
            with self.subTest(turns=turns):
                s_store, a_store = Store(), Store()
                sync, asyn = session_on(s_store, **options), async_on(a_store, **options)

                async def go():
                    out = []
                    for said, reply in zip(turns, replies):
                        stream = await asyn.respond(said, lambda m, reply=reply: _words(reply))
                        spoken = "".join([piece async for piece in stream])
                        if stream.decision.needs_model:
                            self.assertEqual(spoken, reply or "")
                        out.append(stream.decision)
                    return out

                a_decisions = run(go())
                s_decisions = [sync.answer(said, lambda m, reply=reply: reply) for said, reply in zip(turns, replies)]
                self.assertEqual(a_store.writes, s_store.writes)
                self.assertEqual(asyn.transcript, sync.transcript)
                self.assertEqual(asyn.stats(), sync.stats())
                for a, s in zip(a_decisions, s_decisions):
                    self.assertEqual(_fields(a)[2:], _fields(s)[2:])


class LoopTests(unittest.TestCase):
    def test_a_slow_server_never_blocks_the_event_loop(self):
        session = async_on(SlowStore())

        async def go():
            stop, ticks = asyncio.Event(), []
            beat = asyncio.create_task(_heartbeat(stop, ticks))
            await asyncio.sleep(0)
            decision = await session.decide("what is your refund policy")
            stop.set()
            await beat
            return decision, ticks

        decision, ticks = run(go())
        self.assertTrue(decision.needs_model)
        self.assertGreater(len(ticks), 3)  # the loop kept running during a 0.2 s lookup

    def test_a_sync_model_runs_off_the_event_loop(self):
        session = async_on(Store())
        loop_thread = []

        def blocking_model(messages):
            loop_thread.append(threading.current_thread() is threading.main_thread())
            time.sleep(0.2)
            return ANSWER

        async def go():
            stop, ticks = asyncio.Event(), []
            beat = asyncio.create_task(_heartbeat(stop, ticks))
            await asyncio.sleep(0)
            decision = await session.answer("what is your refund policy", blocking_model)
            stop.set()
            await beat
            return decision, ticks

        decision, ticks = run(go())
        self.assertEqual(loop_thread, [False])
        self.assertGreater(len(ticks), 3)
        self.assertTrue(decision.stored)

    def test_an_async_model_runs_on_the_loop(self):
        session = async_on(Store())

        async def model(messages):
            await asyncio.sleep(0)
            return ANSWER

        self.assertTrue(run(session.answer("what is your refund policy", model)).stored)

    def test_fifty_calls_on_a_stuck_server_all_answer_in_time(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(256)
        held, stop = [], threading.Event()

        def accept():
            listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    held.append(listener.accept()[0])
                except OSError:
                    continue

        threading.Thread(target=accept, daemon=True).start()
        try:
            with _env(CROWKIS_PORT=str(listener.getsockname()[1])):
                sessions = [crowkis.async_voice_session() for _ in range(50)]

            async def call(session, n):
                async def model(messages):
                    return f"Refunds arrive within five business days, ticket {n}."
                return await session.answer("how long do refunds usually take to arrive", model)

            async def go():
                stop_beat, ticks = asyncio.Event(), []
                beat = asyncio.create_task(_heartbeat(stop_beat, ticks))
                started = time.monotonic()
                decisions = await asyncio.gather(*(call(s, n) for n, s in enumerate(sessions)))
                took = time.monotonic() - started
                stop_beat.set()
                await beat
                return decisions, took, ticks

            decisions, took, ticks = run(go())
        finally:
            stop.set()
            for conn in held:
                conn.close()
            listener.close()
        self.assertTrue(held)
        self.assertEqual([d.text for d in decisions],
                         [f"Refunds arrive within five business days, ticket {n}." for n in range(50)])
        self.assertTrue(all(not d.stored for d in decisions))
        self.assertLess(took, 5.0)
        self.assertGreater(len(ticks), 20)  # the loop stayed responsive throughout


class RecordAndRespondTests(unittest.TestCase):
    def test_decide_then_record(self):
        store = Store()
        session = async_on(store)

        async def go():
            decision = await session.decide("what is your refund policy")
            return await session.record(decision, ANSWER)

        decision = run(go())
        self.assertTrue(decision.stored)
        self.assertEqual(store.writes, [("what is your refund policy", ANSWER, False)])

    def test_record_refuses_what_the_sync_record_refuses(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        session = async_on(store)

        async def go():
            served = await session.decide("what is your refund policy")
            await session.record(served, "x")

        with self.assertRaises(ValueError):
            run(go())

    def test_respond_takes_async_streams_sync_iterables_strings_and_awaitables(self):
        async def agen(m):
            yield "Here is "
            yield "the answer."

        async def coro(m):
            return ANSWER

        for model in (agen, lambda m: ["Here is ", "the answer."], lambda m: ANSWER, coro):
            with self.subTest(model=model):
                session = async_on(Store())

                async def go():
                    stream = await session.respond("what is your refund policy", model)
                    self.assertIsInstance(stream, AsyncVoiceResponse)
                    return "".join([p async for p in stream]), stream.decision

                spoken, decision = run(go())
                self.assertEqual(spoken, ANSWER)
                self.assertTrue(decision.stored)

    def test_a_blocking_sync_stream_is_read_off_the_loop(self):
        def slow_pieces(messages):
            for piece in ("Here is ", "the answer."):
                time.sleep(0.1)
                yield piece

        session = async_on(Store())

        async def go():
            stop, ticks = asyncio.Event(), []
            beat = asyncio.create_task(_heartbeat(stop, ticks))
            await asyncio.sleep(0)
            stream = await session.respond("what is your refund policy", slow_pieces)
            spoken = "".join([p async for p in stream])
            stop.set()
            await beat
            return spoken, ticks

        spoken, ticks = run(go())
        self.assertEqual(spoken, ANSWER)
        self.assertGreater(len(ticks), 3)

    def test_a_cache_hit_never_calls_the_model(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        session = async_on(store)

        async def go():
            stream = await session.respond("what is your refund policy", lambda m: self.fail("model called"))
            return [p async for p in stream], stream.decision

        pieces, decision = run(go())
        self.assertEqual(pieces, [ANSWER])
        self.assertTrue(decision.served_from_cache)

    def test_a_barge_in_stops_the_stream_closes_the_model_and_stores_nothing(self):
        store = Store()
        session = async_on(store)
        closed = []

        async def model(m):
            try:
                for piece in ("Refunds ", "take ", "five ", "days."):
                    yield piece
            finally:
                closed.append(True)

        async def go():
            stream = await session.respond("what is your refund policy", model)
            spoken = []
            async for piece in stream:
                spoken.append(piece)
                if len(spoken) == 2:
                    session.cancel()
            return spoken, stream.decision

        spoken, decision = run(go())
        self.assertEqual(spoken, ["Refunds ", "take "])
        self.assertEqual(closed, [True])
        self.assertFalse(decision.stored)
        self.assertFalse(decision.empty)
        self.assertIn("moved on", decision.not_stored)
        self.assertEqual(store.writes, [])

    def test_talked_over_before_the_first_read_never_calls_the_model(self):
        session = async_on(Store())

        async def go():
            stream = await session.respond("what is your refund policy", lambda m: self.fail("model called"))
            session.cancel()
            return [p async for p in stream], stream.decision

        pieces, decision = run(go())
        self.assertEqual(pieces, [])
        self.assertFalse(decision.empty)

    def test_a_model_error_stores_nothing_and_stopping_early_stores_nothing(self):
        store = Store()
        session = async_on(store)

        async def broken(m):
            yield "Refunds "
            raise RuntimeError("model stream broke")

        async def go():
            stream = await session.respond("what is your refund policy", broken)
            with self.assertRaises(RuntimeError):
                async for _ in stream:
                    pass
            stream = await session.respond("how do I reset my password", lambda m: ["Open ", "settings."])
            async for _ in stream:
                break
            await stream.close()

        run(go())
        self.assertEqual(store.writes, [])

    def test_a_stream_is_read_once(self):
        session = async_on(Store())

        async def go():
            stream = await session.respond("what is your refund policy", lambda m: [ANSWER])
            _ = [p async for p in stream]
            with self.assertRaises(RuntimeError):
                stream.__aiter__()

        run(go())


class SurfaceTests(unittest.TestCase):
    def test_exports(self):
        self.assertIn("AsyncVoiceSession", crowkis.__all__)
        self.assertIn("async_voice_session", crowkis.__all__)
        self.assertIn("AsyncVoiceResponse", crowkis.__all__)

    def test_wraps_a_session_and_passes_the_quick_calls_through(self):
        store = Store()
        sync = session_on(store, fillers={"hello": "Hi!"})
        session = AsyncVoiceSession.wrap(sync)
        self.assertIs(session.session, sync)
        self.assertIs(session.agent, sync.agent)
        self.assertEqual(session.voice, "v")
        session.set_values(name="Asha")
        self.assertEqual(sync.values, {"name": "Asha"})
        session.register_filler("thanks", "You're welcome!")
        self.assertEqual(run(session.decide("thanks")).text, "You're welcome!")
        self.assertEqual(session.stats(), sync.stats())
        self.assertEqual(session.injections(), sync.injections())
        self.assertTrue(session.cancel())  # the filler turn was still open: cancel reaches the session
        self.assertEqual(sync.barge_ins, 1)

    def test_constructed_like_a_voice_session(self):
        session = AsyncVoiceSession(Agent("caller", client=Store()), voice="v", serve_above=0.95)
        self.assertIsInstance(session.session, VoiceSession)
        self.assertEqual(session.session.serve_above, 0.95)

    def test_async_voice_session_has_the_live_call_defaults(self):
        with _env(CROWKIS_HOST="10.0.0.5", CROWKIS_TENANT="my-app"):
            session = crowkis.async_voice_session(voice="eleven-rachel")
        self.assertIsInstance(session, AsyncVoiceSession)
        self.assertEqual(session.session.latency_budget_ms, 250)
        client = session.agent._client
        self.assertEqual((client.host, client.tenant, client.read_timeout, client.max_retries),
                         ("10.0.0.5", "my-app", 1.0, 0))
        self.assertEqual(session.voice, "eleven-rachel")

    def test_report_stats_and_close_are_async(self):
        session = async_on(Store())
        with mock.patch.object(session.session, "report_stats", return_value=True) as report:
            self.assertTrue(run(session.report_stats()))
        report.assert_called_once()
        with mock.patch.object(session.agent, "close") as close:
            run(session.close())
        close.assert_called_once()

    def test_the_sync_respond_points_an_async_model_to_the_async_session(self):
        async def model(messages):
            return ANSWER

        with self.assertRaises(TypeError) as caught:
            list(session_on(Store()).respond("what is your refund policy", model))
        self.assertIn("async_voice_session", str(caught.exception))


class ReviewFollowUpTests(unittest.TestCase):
    def test_a_slow_sync_model_never_makes_a_lookup_wait_for_a_thread(self):
        # 100 calls in a blocking 0.5 s model at once: a new call still decides at once.
        store = Store()
        sessions = [async_on(store) for _ in range(100)]
        newcomer = async_on(store)

        def slow_model(messages):
            time.sleep(0.5)
            return ANSWER

        async def go():
            busy = [asyncio.create_task(s.answer("what is your refund policy", slow_model)) for s in sessions]
            await asyncio.sleep(0.1)  # every model call is now holding a thread
            started = time.monotonic()
            await newcomer.decide("how do I reset my password")
            waited = time.monotonic() - started
            await asyncio.gather(*busy)
            return waited

        self.assertLess(run(go()), 0.3)

    def test_an_async_stream_with_only_close_is_closed(self):
        # The OpenAI and Anthropic async streams have async close(), not aclose().
        closed = []

        class ProviderStream:
            def __init__(self):
                self.pieces = iter(["Refunds ", "take ", "five ", "days."])

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.pieces)
                except StopIteration:
                    raise StopAsyncIteration

            async def close(self):
                closed.append(True)

        session = async_on(Store())

        async def go():
            stream = await session.respond("what is your refund policy", lambda m: ProviderStream())
            async for piece in stream:
                session.cancel()

        run(go())
        self.assertEqual(closed, [True])

    def test_a_consuming_task_cancelled_mid_stream_stores_nothing(self):
        for kind in ("async", "sync"):
            with self.subTest(kind=kind):
                store = Store()
                session = async_on(store)
                closed = threading.Event()
                gate = threading.Event()

                def sync_model(m):
                    try:
                        yield "Refunds "
                        gate.wait(2)  # still reading when the task is cancelled
                        yield "take "
                    finally:
                        closed.set()

                async def async_model(m):
                    try:
                        yield "Refunds "
                        await asyncio.sleep(10)
                        yield "take "
                    finally:
                        closed.set()

                async def consume(stream):
                    async for _ in stream:
                        pass

                async def go():
                    stream = await session.respond("what is your refund policy",
                                                   async_model if kind == "async" else sync_model)
                    task = asyncio.create_task(consume(stream))
                    await asyncio.sleep(0.1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    gate.set()
                    return stream.decision

                decision = run(go())
                self.assertTrue(closed.wait(2))
                self.assertFalse(decision.stored)
                self.assertEqual(store.writes, [])

    def test_breaking_out_without_close_stores_nothing(self):
        import gc

        store = Store()
        session = async_on(store)

        async def go():
            stream = await session.respond("what is your refund policy", lambda m: ["Refunds ", "take ", "days."])
            async for _ in stream:
                break
            del stream
            gc.collect()
            await asyncio.sleep(0.05)

        run(go())
        self.assertEqual(store.writes, [])

    def test_the_given_pools_are_used(self):
        import concurrent.futures

        class Counting(concurrent.futures.ThreadPoolExecutor):
            def __init__(self):
                super().__init__(max_workers=4)
                self.jobs = 0

            def submit(self, *args, **kwargs):
                self.jobs += 1
                return super().submit(*args, **kwargs)

        server, model = Counting(), Counting()
        try:
            with _env():
                session = crowkis.async_voice_session(executor=server, model_executor=model)
            session.agent._client = Store()
            session.agent._owns_client = False
            run(session.answer("what is your refund policy", lambda m: ANSWER))
            self.assertGreaterEqual(server.jobs, 2)  # decide, then saving the answer
            self.assertEqual(model.jobs, 1)          # the sync model
        finally:
            server.shutdown()
            model.shutdown()

    def test_setting_an_attribute_changes_the_session(self):
        sync = session_on(Store())
        session = AsyncVoiceSession.wrap(sync)
        session.latency_budget_ms = 400
        session.serve_above = 0.97
        self.assertEqual((sync.latency_budget_ms, sync.serve_above), (400, 0.97))
        self.assertEqual(session.latency_budget_ms, 400)


if __name__ == "__main__":
    unittest.main()
