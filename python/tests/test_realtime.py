"""Server-free tests for crowkis.RealtimeAdapter and crowkis.RealtimeGate.

No network, no websocket: a fake client stands in for CrowkisClient so the
speech-to-speech turn gate is verified in isolation — what it injects, what it
suppresses, and above all that it never suppresses the respond event on a miss.
Run:  python3 -m unittest discover -s tests -q
"""

import unittest

from crowkis.agent import Agent
from crowkis.client import CacheHit
from crowkis.realtime import RealtimeAdapter, RealtimeGate
from crowkis.voice import VoiceSession

TRANSCRIPT_EVENT = "provider.transcript.done"
INJECT_EVENT = "provider.item.add"
RESPOND_EVENT = "provider.respond.now"


class FakeClient:
    def __init__(self, confidence=0.99):
        self.confidence = confidence
        self.shared = {}
        self.reads = []
        self.writes = []

    def cget_hit(self, query, **kwargs):
        self.reads.append(query)
        response = self.shared.get(query)
        if response is None:
            return None
        return CacheHit(
            response=response.encode(),
            similarity=0.99,
            ttl_remaining=600,
            matched_key=b"k",
            confidence=self.confidence,
            hit_type="semantic",
        )

    def cset(self, query, response, *, ttl=None, tenant=None, template=False):
        self.writes.append(query)
        self.shared[query] = response

    def ctoolget(self, tool, args_str, *, tenant=None):
        return None

    def ctoolset(self, tool, args_str, result, *, ex=None, tenant=None):
        return None

    def close(self):
        return None


class ExplodingSession:
    def __init__(self):
        self.calls = 0

    def decide(self, caller_said):
        self.calls += 1
        raise RuntimeError("the cache connection dropped mid-call")


def adapter(transcript_field="transcript"):
    return RealtimeAdapter(
        transcript_event=TRANSCRIPT_EVENT,
        transcript_field=transcript_field,
        inject_event=INJECT_EVENT,
        respond_event=RESPOND_EVENT,
    )


def session(client, **kwargs):
    return VoiceSession(Agent("voice-gate", client=client), voice="v1", **kwargs)


def transcript_event(text, field="transcript"):
    return {"type": TRANSCRIPT_EVENT, field: text}


def types(events):
    return [event["type"] for event in events]


class AdapterValidationTests(unittest.TestCase):
    def test_every_event_name_is_refused_when_blank_or_not_a_string(self):
        good = {
            "transcript_event": TRANSCRIPT_EVENT,
            "transcript_field": "transcript",
            "inject_event": INJECT_EVENT,
            "respond_event": RESPOND_EVENT,
            "role_field": "role",
            "text_field": "text",
        }
        for name in good:
            for bad in ("", "   ", None, 7, [], {}):
                with self.subTest(name=name, bad=bad):
                    args = dict(good)
                    args[name] = bad
                    with self.assertRaises(ValueError):
                        RealtimeAdapter(**args)

    def test_a_dotted_path_with_an_empty_segment_is_refused(self):
        for bad in ("a..b", ".transcript", "transcript."):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    adapter(transcript_field=bad)

    def test_the_same_arguments_that_fail_blank_succeed_when_named(self):
        built = adapter()
        self.assertEqual(built.transcript_event, TRANSCRIPT_EVENT)
        self.assertEqual(built.respond()["type"], RESPOND_EVENT)

    def test_the_gate_refuses_anything_that_is_not_an_adapter_or_a_session(self):
        client = FakeClient()
        with self.assertRaises(TypeError):
            RealtimeGate(session(client), object())
        with self.assertRaises(TypeError):
            RealtimeGate(object(), adapter())


class RoutingTests(unittest.TestCase):
    def test_an_unrelated_event_returns_nothing_and_never_asks_the_cache(self):
        client = FakeClient()
        gate = RealtimeGate(session(client), adapter())

        self.assertEqual(gate.handle({"type": "provider.audio.delta"}), [])
        self.assertEqual(client.reads, [])
        self.assertEqual(gate.stats()["transcripts"], 0)

        client.shared["what does the pro plan cost"] = "It is forty dollars a month."
        gate.handle(transcript_event("what does the pro plan cost"))
        self.assertEqual(client.reads, ["what does the pro plan cost"])
        self.assertEqual(gate.stats()["transcripts"], 1)

    def test_a_hit_injects_two_turns_and_sends_no_respond_event(self):
        client = FakeClient()
        client.shared["what does the pro plan cost"] = "It is forty dollars a month."
        gate = RealtimeGate(session(client), adapter())

        out = gate.handle(transcript_event("what does the pro plan cost"))

        self.assertEqual(types(out), [INJECT_EVENT, INJECT_EVENT])
        self.assertNotIn(RESPOND_EVENT, types(out))
        self.assertEqual([e["role"] for e in out], ["user", "assistant"])
        self.assertEqual(gate.stats()["served"], 1)
        self.assertEqual(gate.stats()["suppressed"], 1)
        self.assertEqual(gate.stats()["forwarded"], 0)

    def test_a_miss_sends_exactly_one_respond_event_and_injects_nothing(self):
        client = FakeClient()
        gate = RealtimeGate(session(client), adapter())

        out = gate.handle(transcript_event("what does the pro plan cost"))

        self.assertEqual(types(out), [RESPOND_EVENT])
        self.assertNotIn(INJECT_EVENT, types(out))
        self.assertEqual(gate.stats()["served"], 0)
        self.assertEqual(gate.stats()["suppressed"], 0)
        self.assertEqual(gate.stats()["forwarded"], 1)

    def test_an_unconfident_hit_is_forwarded_not_served(self):
        client = FakeClient(confidence=0.10)
        client.shared["what does the pro plan cost"] = "It is forty dollars a month."
        gate = RealtimeGate(session(client), adapter())

        self.assertEqual(
            types(gate.handle(transcript_event("what does the pro plan cost"))),
            [RESPOND_EVENT],
        )

        client.confidence = 0.99
        self.assertEqual(
            types(gate.handle(transcript_event("what does the pro plan cost"))),
            [INJECT_EVENT, INJECT_EVENT],
        )

    def test_an_empty_transcript_is_forwarded_rather_than_matched(self):
        client = FakeClient()
        client.shared[""] = "never spoken"
        gate = RealtimeGate(session(client), adapter())

        for blank in ("", "   ", "\n\t"):
            with self.subTest(blank=blank):
                self.assertEqual(
                    types(gate.handle(transcript_event(blank))), [RESPOND_EVENT]
                )
        self.assertEqual(client.reads, [])
        self.assertEqual(gate.stats()["forwarded"], 3)


class NestedTranscriptTests(unittest.TestCase):
    def test_a_dotted_field_resolves_a_nested_transcript(self):
        client = FakeClient()
        client.shared["where is my nearest branch"] = "Two streets over."
        built = adapter(transcript_field="content.input.transcript")
        gate = RealtimeGate(session(client), built)

        event = {
            "type": TRANSCRIPT_EVENT,
            "content": {"input": {"transcript": "where is my nearest branch"}},
        }
        self.assertEqual(built.transcript_of(event), "where is my nearest branch")
        self.assertEqual(types(gate.handle(event)), [INJECT_EVENT, INJECT_EVENT])

    def test_the_same_text_at_the_wrong_depth_is_not_found(self):
        built = adapter(transcript_field="content.input.transcript")
        flat = {"type": TRANSCRIPT_EVENT, "transcript": "where is my nearest branch"}
        self.assertIsNone(built.transcript_of(flat))

        client = FakeClient()
        client.shared["where is my nearest branch"] = "Two streets over."
        gate = RealtimeGate(session(client), built)
        self.assertEqual(types(gate.handle(flat)), [RESPOND_EVENT])

    def test_an_event_keyed_by_name_instead_of_type_still_matches(self):
        built = RealtimeAdapter(
            transcript_event="serverInput",
            transcript_field="serverInput.transcription.text",
            inject_event=INJECT_EVENT,
            respond_event=RESPOND_EVENT,
        )
        event = {"serverInput": {"transcription": {"text": "do you ship overseas"}}}
        self.assertEqual(built.transcript_of(event), "do you ship overseas")
        self.assertIsNone(built.transcript_of({"otherInput": {"text": "hello"}}))


class SpokenTextTests(unittest.TestCase):
    def test_the_injected_assistant_text_is_exactly_what_was_spoken(self):
        spoken = "The pro plan is forty dollars a month."
        client = FakeClient()
        client.shared["what does the pro plan cost"] = spoken
        gate = RealtimeGate(session(client), adapter())

        out = gate.handle(transcript_event("what does the pro plan cost"))

        self.assertEqual(out[0]["text"], "what does the pro plan cost")
        self.assertEqual(out[1]["text"], spoken)
        self.assertEqual(gate.pending_decision.text, spoken)
        self.assertEqual(out[1]["text"], gate.pending_decision.text)

    def test_a_different_cached_answer_changes_the_injected_text(self):
        client = FakeClient()
        client.shared["what does the pro plan cost"] = "Forty dollars."
        gate = RealtimeGate(session(client), adapter())
        first = gate.handle(transcript_event("what does the pro plan cost"))

        client.shared["what does the pro plan cost"] = "Fifty dollars."
        second = gate.handle(transcript_event("what does the pro plan cost"))

        self.assertEqual(first[1]["text"], "Forty dollars.")
        self.assertEqual(second[1]["text"], "Fifty dollars.")
        self.assertNotEqual(first[1]["text"], second[1]["text"])

    def test_served_audio_is_reachable_and_cleared_on_the_next_turn(self):
        client = FakeClient()
        client.shared["what does the pro plan cost"] = "Forty dollars."
        gate = RealtimeGate(
            session(client, synthesise=lambda text: text.encode()), adapter()
        )

        gate.handle(transcript_event("what does the pro plan cost"))
        self.assertEqual(gate.pending_audio, b"Forty dollars.")

        gate.handle(transcript_event("what is the weather like today"))
        self.assertIsNone(gate.pending_audio)
        self.assertIsNone(gate.pending_decision)


class MalformedEventTests(unittest.TestCase):
    SHAPES = [
        {},
        None,
        [],
        "a bare string",
        42,
        {"type": None},
        {"type": TRANSCRIPT_EVENT},
        {"type": TRANSCRIPT_EVENT, "transcript": None},
        {"type": TRANSCRIPT_EVENT, "transcript": 17},
        {"type": TRANSCRIPT_EVENT, "transcript": ["nested", "nonsense"]},
        {"type": TRANSCRIPT_EVENT, "transcript": {"deeply": {"nested": {}}}},
        [{"type": TRANSCRIPT_EVENT, "transcript": "in a list"}],
        {TRANSCRIPT_EVENT: None},
    ]

    def test_no_shape_ever_raises_and_none_of_them_is_served(self):
        self.assertGreaterEqual(len(self.SHAPES), 6)
        client = FakeClient()
        gate = RealtimeGate(session(client), adapter())

        for shape in self.SHAPES:
            with self.subTest(shape=repr(shape)):
                out = gate.handle(shape)
                self.assertIn(types(out), ([], [RESPOND_EVENT]))

        self.assertEqual(gate.stats()["served"], 0)
        self.assertEqual(gate.stats()["suppressed"], 0)
        self.assertEqual(gate.stats()["events"], len(self.SHAPES))

    def test_a_nested_dotted_path_survives_the_same_garbage(self):
        gate = RealtimeGate(
            session(FakeClient()), adapter(transcript_field="a.b.transcript")
        )
        for shape in self.SHAPES + [
            {"type": TRANSCRIPT_EVENT, "a": None},
            {"type": TRANSCRIPT_EVENT, "a": {"b": []}},
            {"type": TRANSCRIPT_EVENT, "a": {"b": {"transcript": 1.5}}},
        ]:
            with self.subTest(shape=repr(shape)):
                self.assertIn(types(gate.handle(shape)), ([], [RESPOND_EVENT]))

    def test_a_session_that_raises_forwards_instead_of_killing_the_call(self):
        broken = ExplodingSession()
        gate = RealtimeGate(broken, adapter())

        out = gate.handle(transcript_event("what does the pro plan cost"))

        self.assertEqual(types(out), [RESPOND_EVENT])
        self.assertEqual(broken.calls, 1)
        self.assertEqual(gate.stats()["suppressed"], 0)


class SuppressionAccountingTests(unittest.TestCase):
    def test_suppressed_counts_exactly_the_avoided_inferences(self):
        client = FakeClient()
        cached = [
            "what does the pro plan cost",
            "what are your opening hours",
            "do you ship internationally",
        ]
        for question in cached:
            client.shared[question] = f"answer to {question}"
        gate = RealtimeGate(session(client), adapter())

        script = cached + [
            "how much does a courier collection cost",
            "what does the pro plan cost",
            "when is the next public holiday",
            "what are your opening hours",
            {"type": "provider.audio.delta"},
            "",
        ]
        expected_hits = 5

        for turn in script:
            gate.handle(turn if isinstance(turn, dict) else transcript_event(turn))

        stats = gate.stats()
        self.assertEqual(stats["suppressed"], expected_hits)
        self.assertEqual(stats["served"], expected_hits)
        self.assertEqual(stats["forwarded"], 3)
        self.assertEqual(stats["events"], len(script))
        self.assertEqual(stats["transcripts"], len(script) - 2)
        self.assertNotEqual(stats["suppressed"], stats["events"])

    def test_nothing_is_suppressed_when_the_cache_is_empty(self):
        client = FakeClient()
        gate = RealtimeGate(session(client), adapter())
        for _ in range(5):
            gate.handle(transcript_event("what does the pro plan cost"))
        self.assertEqual(gate.stats()["suppressed"], 0)
        self.assertEqual(gate.stats()["forwarded"], 5)


class NeverSuppressAMissTests(unittest.TestCase):
    def test_every_miss_across_twenty_turns_still_gets_a_respond_event(self):
        client = FakeClient()
        known = {
            "what does the pro plan cost": "Forty dollars a month.",
            "what are your opening hours": "Nine until five, weekdays.",
            "do you ship internationally": "Yes, to most countries.",
            "how do i reset a password": "From the sign-in screen.",
        }
        client.shared.update(known)
        gate = RealtimeGate(session(client), adapter())

        script = []
        unknown = [
            "what is the courier collection cutoff",
            "when is the next public holiday",
            "do you have a student discount",
            "what is the warranty period",
            "can i change my delivery window",
            "where are your warehouses located",
        ]
        for index in range(20):
            if index % 3 == 0:
                script.append(unknown[(index // 3) % len(unknown)])
            else:
                script.append(list(known)[index % len(known)])

        misses = 0
        hits = 0
        for said in script:
            out = gate.handle(transcript_event(said))
            if said in known:
                hits += 1
                self.assertEqual(types(out), [INJECT_EVENT, INJECT_EVENT])
            else:
                misses += 1
                self.assertEqual(
                    types(out),
                    [RESPOND_EVENT],
                    f"a miss on {said!r} produced no respond event: a silent dead call",
                )

        self.assertEqual(len(script), 20)
        self.assertGreater(misses, 0)
        self.assertGreater(hits, 0)
        self.assertEqual(gate.stats()["forwarded"], misses)
        self.assertEqual(gate.stats()["suppressed"], hits)

    def test_a_run_of_pure_misses_forwards_every_single_turn(self):
        client = FakeClient()
        gate = RealtimeGate(session(client), adapter())
        for index in range(20):
            out = gate.handle(transcript_event(f"an unseen question number {index}"))
            self.assertEqual(types(out), [RESPOND_EVENT])
        self.assertEqual(gate.stats()["forwarded"], 20)
        self.assertEqual(gate.stats()["suppressed"], 0)


if __name__ == "__main__":
    unittest.main()
