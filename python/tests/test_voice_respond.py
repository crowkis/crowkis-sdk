"""VoiceSession.respond(): the text to speak, piece by piece, as the model writes it.

respond() decides at once (stream.decision is ready before the first piece). A turn the
cache or a filler answers yields that text and never calls the model. A model turn
streams the model's pieces and records the full answer when the stream ends, under the
same rules as answer(). The stream stops, closes the model's stream and stores nothing
when the caller talks over it (cancel()) or a newer turn is decided; an error or a
consumer that stops early stores nothing either."""

import unittest

from crowkis import VoiceResponse

from test_voice_record import CALLS, _fields
from test_voice_stress_bugs import ANSWER, Store, session_on


def _words(text):
    """A stand-in streaming model: the answer in word-sized pieces."""
    if not text:
        return iter([text] if text is not None else [])
    words = text.split(" ")
    return iter([w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)])


class _Upstream:
    """A model stream that records whether it was read to the end or closed."""

    def __init__(self, pieces, fail_at=None):
        self.pieces = list(pieces)
        self.fail_at = fail_at
        self.read = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.fail_at is not None and self.read == self.fail_at:
            raise RuntimeError("model stream broke")
        if self.read >= len(self.pieces):
            raise StopIteration
        self.read += 1
        return self.pieces[self.read - 1]

    def close(self):
        self.closed = True


class SameAsAnswerTests(unittest.TestCase):
    def test_streaming_ends_exactly_as_answer_does(self):
        for turns, replies, options in CALLS:
            with self.subTest(turns=turns):
                a_store, r_store = Store(), Store()
                a_session, r_session = session_on(a_store, **options), session_on(r_store, **options)
                a_decisions, r_decisions = [], []
                for said, reply in zip(turns, replies):
                    a_decisions.append(a_session.answer(said, lambda messages, reply=reply: reply))
                    stream = r_session.respond(said, lambda messages, reply=reply: _words(reply))
                    spoken = "".join(stream)
                    r_decisions.append(stream.decision)
                    if stream.decision.needs_model:
                        self.assertEqual(spoken, reply or "")
                self.assertEqual(r_store.writes, a_store.writes)
                self.assertEqual(r_session.transcript, a_session.transcript)
                self.assertEqual(r_session.stats(), a_session.stats())
                for a, r in zip(a_decisions, r_decisions):
                    # answer() keeps whatever the model returned (None too); a stream joins text.
                    self.assertEqual(_fields(r)[2:], _fields(a)[2:])
                    self.assertEqual(r.text or "", a.text or "")


class StreamTests(unittest.TestCase):
    def test_pieces_come_through_as_the_model_writes_them(self):
        session = session_on(Store())
        stream = session.respond("what is your refund policy", lambda messages: iter(["Refunds ", "take ", "five days."]))
        self.assertIsInstance(stream, VoiceResponse)
        self.assertEqual(list(stream), ["Refunds ", "take ", "five days."])
        self.assertTrue(stream.decision.stored)
        self.assertEqual(stream.decision.text, "Refunds take five days.")

    def test_the_decision_is_ready_before_the_model_is_called(self):
        called = []
        session = session_on(Store())
        stream = session.respond("what is your refund policy", lambda messages: called.append(1) or iter([ANSWER]))
        self.assertTrue(stream.decision.needs_model)
        self.assertEqual(called, [])
        list(stream)
        self.assertEqual(called, [1])

    def test_a_cache_hit_yields_the_cached_answer_and_never_calls_the_model(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        stream = session_on(store).respond("what is your refund policy", lambda messages: self.fail("model called"))
        self.assertTrue(stream.decision.served_from_cache)
        self.assertEqual(list(stream), [ANSWER])

    def test_cached_audio_is_on_the_decision(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        session = session_on(store, synthesise=lambda text: b"pcm:" + text.encode())
        stream = session.respond("what is your refund policy", lambda messages: self.fail("model called"))
        self.assertEqual(stream.decision.audio, b"pcm:" + ANSWER.encode())

    def test_a_filler_yields_its_reply(self):
        stream = session_on(Store(), fillers={"hello": "Hi, how can I help?"}).respond(
            "hello", lambda messages: self.fail("model called"))
        self.assertEqual(list(stream), ["Hi, how can I help?"])

    def test_a_model_that_returns_a_whole_string_is_one_piece(self):
        stream = session_on(Store()).respond("what is your refund policy", lambda messages: ANSWER)
        self.assertEqual(list(stream), [ANSWER])
        self.assertTrue(stream.decision.stored)

    def test_the_model_reads_the_system_prompt_then_the_chosen_messages(self):
        seen = []
        session = session_on(Store())
        list(session.respond("what is your refund policy", lambda m: seen.append(m) or iter([ANSWER]), system="Be brief."))
        self.assertEqual(seen, [[{"role": "system", "content": "Be brief."},
                                 {"role": "user", "content": "what is your refund policy"}]])
        seen.clear()
        list(session.respond("my order 48213 has not arrived where is it", lambda m: seen.append(m) or iter([ANSWER])))
        self.assertEqual(seen[0][-1], {"role": "user", "content": "my order 48213 has not arrived where is it"})
        self.assertEqual(len(seen[0]), 3)  # the whole call: the earlier turn, its answer, this turn

    def test_none_pieces_are_skipped_and_other_types_refused(self):
        session = session_on(Store())
        self.assertEqual(list(session.respond("what is your refund policy", lambda m: iter(["A", None, "B"]))), ["A", "B"])
        with self.assertRaises(TypeError) as caught:
            list(session.respond("how do I reset my password", lambda m: iter([{"choices": []}])))
        self.assertIn("text", str(caught.exception))

    def test_private_keeps_the_answer_to_this_call(self):
        store = Store()
        stream = session_on(store).respond("what is your refund policy", lambda m: iter([ANSWER]), private=True)
        list(stream)
        self.assertFalse(stream.decision.stored)
        self.assertEqual(store.writes, [])

    def test_an_empty_stream_is_an_empty_answer(self):
        stream = session_on(Store()).respond("what is your refund policy", lambda m: iter([]))
        self.assertEqual(list(stream), [])
        self.assertTrue(stream.decision.empty)
        self.assertFalse(stream.decision.stored)

    def test_a_stream_is_read_once(self):
        stream = session_on(Store()).respond("what is your refund policy", lambda m: iter([ANSWER]))
        list(stream)
        with self.assertRaises(RuntimeError):
            list(stream)


class StopTests(unittest.TestCase):
    def test_a_barge_in_stops_the_stream_and_stores_nothing(self):
        store = Store()
        session = session_on(store)
        upstream = _Upstream(["Refunds ", "take ", "five ", "days."])
        stream = session.respond("what is your refund policy", lambda m: upstream)
        spoken = []
        for piece in stream:
            spoken.append(piece)
            if len(spoken) == 2:
                session.cancel()
        self.assertEqual(spoken, ["Refunds ", "take "])
        self.assertTrue(upstream.closed)
        self.assertLess(upstream.read, 4)
        self.assertFalse(stream.decision.stored)
        self.assertIn("moved on", stream.decision.not_stored)
        self.assertEqual(store.writes, [])
        self.assertEqual(session.transcript, [])

    def test_a_newer_turn_stops_the_older_stream(self):
        store = Store()
        session = session_on(store)
        upstream = _Upstream(["Refunds ", "take ", "five ", "days."])
        stream = session.respond("what is your refund policy", lambda m: upstream)
        iterator = iter(stream)
        self.assertEqual(next(iterator), "Refunds ")
        session.decide("how do I reset my password")
        self.assertEqual(list(iterator), [])
        self.assertTrue(upstream.closed)
        self.assertFalse(stream.decision.stored)
        self.assertEqual(store.writes, [])

    def test_a_model_error_propagates_and_stores_nothing(self):
        store = Store()
        session = session_on(store)
        upstream = _Upstream(["Refunds ", "take "], fail_at=1)
        stream = session.respond("what is your refund policy", lambda m: upstream)
        with self.assertRaises(RuntimeError):
            list(stream)
        self.assertTrue(upstream.closed)
        self.assertEqual(store.writes, [])
        self.assertFalse(stream.decision.stored)
        # The turn is still the caller's: the app may record its own fallback.
        session.record(stream.decision, "Sorry, let me check that for you.")
        self.assertTrue(stream.decision.stored)

    def test_a_consumer_that_stops_early_stores_nothing(self):
        store = Store()
        session = session_on(store)
        upstream = _Upstream(["Refunds ", "take ", "five ", "days."])
        stream = session.respond("what is your refund policy", lambda m: upstream)
        for piece in stream:
            break
        stream.close()
        self.assertTrue(upstream.closed)
        self.assertEqual(store.writes, [])
        self.assertFalse(stream.decision.stored)


class ReviewFollowUpTests(unittest.TestCase):
    def test_talked_over_before_the_first_read_never_calls_the_model_and_is_not_empty(self):
        store = Store()
        session = session_on(store)
        stream = session.respond("what is your refund policy", lambda m: self.fail("model called"))
        session.cancel()
        self.assertEqual(list(stream), [])
        self.assertFalse(stream.decision.empty)  # not "retry": the caller has moved on
        self.assertIn("moved on", stream.decision.not_stored)
        self.assertEqual(store.writes, [])

    def test_works_when_decide_is_overridden(self):
        from crowkis import Agent, TurnDecision, VoiceSession

        class Custom(VoiceSession):
            def decide(self, caller_said):
                original = super().decide(caller_said)
                copy = TurnDecision(original.action, text=original.text, reason=original.reason)
                copy.messages, copy.cacheable, copy.turn = original.messages, original.cacheable, original.turn
                copy._session = original._session
                return copy

        store, seen = Store(), []
        session = Custom(Agent("caller", client=store), voice="v")
        list(session.respond("my order 48213 has not arrived where is it", lambda m: seen.append(m) or iter([ANSWER])))
        self.assertEqual(seen[0][-1], {"role": "user", "content": "my order 48213 has not arrived where is it"})
        self.assertEqual(session.transcript[0], {"role": "user", "content": "my order 48213 has not arrived where is it"})

    def test_a_model_stream_whose_close_fails_is_still_recorded(self):
        class BadClose(_Upstream):
            def close(self):
                raise OSError("socket already gone")

        store = Store()
        stream = session_on(store).respond("what is your refund policy", lambda m: BadClose([ANSWER]))
        self.assertEqual(list(stream), [ANSWER])
        self.assertTrue(stream.decision.stored)

    def test_a_partly_read_stream_that_is_dropped_stores_nothing(self):
        import gc

        store = Store()
        session = session_on(store)
        stream = session.respond("what is your refund policy", lambda m: iter(["Refunds ", "take ", "days."]))
        iterator = iter(stream)
        next(iterator)
        del iterator, stream
        gc.collect()
        self.assertEqual(store.writes, [])

    def test_recording_mid_stream_stops_the_stream(self):
        store = Store()
        session = session_on(store)
        stream = session.respond("what is your refund policy", lambda m: iter(["Refunds ", "take ", "days."]))
        iterator = iter(stream)
        next(iterator)
        session.record(stream.decision, "Refunds take five business days.")
        self.assertEqual(list(iterator), [])
        self.assertEqual(store.writes, [("what is your refund policy", "Refunds take five business days.", False)])

    def test_cancel_from_another_thread_stops_the_stream(self):
        import threading

        store = Store()
        session = session_on(store)
        gate = threading.Event()

        def model(messages):
            yield "Refunds "
            gate.wait(2)
            yield "take "
            yield "days."

        stream = session.respond("what is your refund policy", model)
        iterator = iter(stream)
        self.assertEqual(next(iterator), "Refunds ")
        threading.Thread(target=lambda: (session.cancel(), gate.set())).start()
        self.assertEqual(list(iterator), [])
        self.assertEqual(store.writes, [])

    def test_empty_pieces_unicode_and_a_long_stream(self):
        store = Store()
        pieces = ["", "\u0930\u093f\u092b\u0902\u0921 ", "\U0001f44d ", "", "five days."]
        stream = session_on(store).respond("what is your refund policy", lambda m: iter(pieces))
        self.assertEqual(list(stream), [p for p in pieces if p])
        self.assertEqual(stream.decision.text, "".join(pieces))
        long = ["word "] * 10000
        stream = session_on(Store()).respond("how do I reset my password", lambda m: iter(long))
        self.assertEqual(sum(1 for _ in stream), 10000)
        self.assertTrue(stream.decision.stored)

    def test_an_async_model_bytes_or_a_number_get_a_clear_error(self):
        async def async_model(messages):
            return ANSWER

        for model, words in ((async_model, "async"), (lambda m: b"bytes", "bytes"), (lambda m: 42, "int")):
            with self.subTest(words=words), self.assertRaises(TypeError) as caught:
                list(session_on(Store()).respond("what is your refund policy", model))
            self.assertIn(words, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
