"""Server-free tests for crowkis.Agent and crowkis.VoiceSession.

No network, no live server: a fake client stands in for CrowkisClient and records
every command, so tool caching, ask() routing, TTS reuse and turn decisions are
verified in isolation. Run:  python -m pytest tests/ -q
"""

import base64
import json
import unittest

from crowkis.agent import Agent
from crowkis.client import CacheHit
from crowkis.voice import VoiceSession, _is_context_dependent, _is_personal


def _hit(confidence, response=b"cached answer", similarity=0.99):
    return CacheHit(
        response=response,
        similarity=similarity,
        ttl_remaining=600,
        matched_key=b"k",
        confidence=confidence,
        hit_type="semantic",
    )


class FakeClient:
    def __init__(self, hit=None):
        self.tools = {}
        self.entries = {}
        self.hit = hit
        self.calls = []

    def kinds(self):
        return [c[0] for c in self.calls]

    def ctoolget(self, tool, args_str, *, tenant=None):
        self.calls.append(("ctoolget", tool, args_str, tenant))
        return self.tools.get((tool, args_str))

    def ctoolset(self, tool, args_str, result, *, ex=None, tenant=None):
        self.calls.append(("ctoolset", tool, args_str, ex, tenant))
        self.tools[(tool, args_str)] = (
            result.encode() if isinstance(result, str) else result
        )

    def cget_hit(self, query, **kwargs):
        self.calls.append(("cget_hit", query, kwargs.get("tenant")))
        return self.hit

    def cset(self, query, response, *, ttl=None, tenant=None, template=False):
        self.calls.append(("cset", query, response, ttl, tenant, template))
        self.entries[query] = response

    def close(self):
        self.calls.append(("close",))


class ScopedFakeClient:
    def __init__(self, confidence=0.99):
        self.confidence = confidence
        self.shared = {}
        self.templates = {}
        self.reads = []
        self.writes = []

    def _store(self, template):
        return self.templates if template else self.shared

    def cget_hit(self, query, **kwargs):
        template = bool(kwargs.get("template"))
        self.reads.append({"query": query, "template": template})
        response = self._store(template).get(query)
        if response is None:
            return None
        if isinstance(response, str):
            response = response.encode()
        return _hit(self.confidence, response=response)

    def cset(self, query, response, *, ttl=None, tenant=None, template=False):
        self.writes.append(
            {
                "query": query,
                "response": response,
                "ttl": ttl,
                "tenant": tenant,
                "template": template,
            }
        )
        self._store(template)[query] = response

    def ctoolget(self, tool, args_str, *, tenant=None):
        return None

    def ctoolset(self, tool, args_str, result, *, ex=None, tenant=None):
        return None

    def close(self):
        return None


def _model_turn(session, caller_said, model_said):
    """One turn answered by the model from decide()'s messages, as answer() runs it."""
    session.decide(caller_said)
    session._record_model_turn(caller_said, model_said)


PERSONAL_UTTERANCES = [
    "when will i get my order",
    "what is my account balance",
    "where is my delivery",
    "what is the status of my claim",
    "how much is my bill this month",
    "has my payment gone through",
    "when does my subscription renew",
    "what is my policy number",
    "is my appointment confirmed",
    "show me my last transaction",
    "did my refund come through",
    "what address is on my account",
    "cancel my order",
    "reschedule my appointment",
    "close my account",
    "update my card",
    "track my parcel",
    "what did my last payment cost",
    "how many tickets do i have on my account",
    "is my refund processed yet",
]

GENERAL_UTTERANCES = [
    "what does the pro plan cost",
    "how do i cancel a subscription",
    "what are your opening hours",
    "how can i improve my sleep",
    "what is the capital of france",
    "do you ship internationally",
    "how do i reset a password",
    "what is the return policy",
    "explain how ordering works",
    "how much does delivery cost",
    "how can i remove a subscription from my account",
    "what payment methods do you take",
    "how do i add a card to my account",
    "steps to enable two factor on my account",
    "can i change the address on my account",
    "where do i find the invoice section",
    "what is your refund policy",
    "how long does delivery take",
    "do you offer a student plan",
    "walk me through setting up my account",
    "how do i configure billing",
    "how much do i pay for invoice",
    "can you walk me through billing setup",
    "where do i configure password",
]


class AgentIdentityTests(unittest.TestCase):
    def test_blank_agent_id_is_refused(self):
        for bad in ("", "   ", None):
            with self.subTest(agent_id=bad):
                with self.assertRaises(ValueError):
                    Agent(bad, client=FakeClient())

    def test_real_agent_id_is_kept_and_trimmed(self):
        agent = Agent("  billing-bot  ", client=FakeClient())
        self.assertEqual(agent.agent_id, "billing-bot")

    def test_does_not_close_borrowed_client(self):
        client = FakeClient()
        Agent("bot", client=client).close()
        self.assertNotIn("close", client.kinds())


class ToolCacheTests(unittest.TestCase):
    def test_same_args_hit_and_different_args_miss(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        runs = []

        @agent.tool
        def lookup(order_id):
            runs.append(order_id)
            return {"status": "shipped", "id": order_id}

        first = lookup(7)
        second = lookup(7)
        self.assertEqual(runs, [7])
        self.assertEqual(first, second)
        self.assertEqual((agent.tool_hits, agent.tool_misses), (1, 1))

        third = lookup(8)
        self.assertEqual(runs, [7, 8])
        self.assertEqual(third, {"status": "shipped", "id": 8})
        self.assertEqual((agent.tool_hits, agent.tool_misses), (1, 2))

    def test_raising_tool_caches_nothing(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        state = {"explode": True}
        runs = []

        @agent.tool
        def flaky(x):
            runs.append(x)
            if state["explode"]:
                raise RuntimeError("upstream down")
            return {"x": x}

        with self.assertRaises(RuntimeError):
            flaky(1)
        self.assertEqual(client.tools, {})
        self.assertNotIn("ctoolset", client.kinds())
        self.assertEqual((agent.tool_hits, agent.tool_misses), (0, 0))

        state["explode"] = False
        self.assertEqual(flaky(1), {"x": 1})
        self.assertEqual(runs, [1, 1])
        self.assertEqual((agent.tool_hits, agent.tool_misses), (0, 1))

    def test_unserialisable_result_always_executes_and_never_throws(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        runs = []

        @agent.tool
        def weird(x):
            runs.append(x)
            return {(1, 2): "tuple keys are not json"}

        first = weird(1)
        second = weird(1)
        self.assertEqual(runs, [1, 1])
        self.assertEqual(first, second)
        self.assertEqual(client.tools, {})
        self.assertEqual(agent.tool_hits, 0)

    def test_identity_keyed_args_degrade_to_always_execute(self):
        class Unhashable:
            __hash__ = None

        client = FakeClient()
        agent = Agent("bot", client=client)
        runs = []

        @agent.tool
        def consume(obj):
            runs.append(obj)
            return "ok"

        self.assertEqual(consume(Unhashable()), "ok")
        self.assertEqual(consume(Unhashable()), "ok")
        self.assertEqual(len(runs), 2)
        self.assertEqual(agent.tool_hits, 0)

    def test_unhashable_container_args_still_cache(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        runs = []

        @agent.tool
        def summarise(payload):
            runs.append(payload)
            return len(payload)

        self.assertEqual(summarise({"a": 1, "b": 2}), 2)
        self.assertEqual(summarise({"b": 2, "a": 1}), 2)
        self.assertEqual(len(runs), 1)
        self.assertEqual(agent.tool_hits, 1)

    def test_tool_name_override_separates_cache_namespaces(self):
        client = FakeClient()
        agent = Agent("bot", client=client)

        @agent.tool(name="crm.customer")
        def fetch(x):
            return x

        fetch(1)
        self.assertEqual(fetch.crowkis_tool_name, "crm.customer")
        self.assertEqual({tool for tool, _ in client.tools}, {"crm.customer"})


class AskRoutingTests(unittest.TestCase):
    def test_high_confidence_serves_from_cache(self):
        agent = Agent("bot", client=FakeClient(hit=_hit(0.95)))
        out = agent.ask("how do refunds work?")
        self.assertEqual(out["route"], "cache")
        self.assertEqual(out["answer"], "cached answer")
        self.assertEqual(agent.route_counts, {"cache": 1, "cheap": 0, "expensive": 0})

    def test_middle_confidence_routes_to_cheap_without_serving_the_answer(self):
        agent = Agent("bot", client=FakeClient(hit=_hit(0.70)))
        out = agent.ask("how do refunds work?")
        self.assertEqual(out["route"], "cheap")
        self.assertIsNone(out["answer"])
        self.assertEqual(out["context"], "cached answer")
        self.assertEqual(agent.route_counts, {"cache": 0, "cheap": 1, "expensive": 0})

    def test_low_confidence_routes_to_expensive(self):
        agent = Agent("bot", client=FakeClient(hit=_hit(0.10)))
        out = agent.ask("how do refunds work?")
        self.assertEqual(out["route"], "expensive")
        self.assertIsNone(out["answer"])
        self.assertEqual(agent.route_counts["expensive"], 1)

    def test_total_miss_routes_to_expensive_with_zero_confidence(self):
        agent = Agent("bot", client=FakeClient(hit=None))
        out = agent.ask("brand new question")
        self.assertEqual(out["route"], "expensive")
        self.assertIsNone(out["answer"])
        self.assertEqual(out["confidence"], 0.0)

    def test_total_miss_reports_similarity_rather_than_omitting_the_key(self):
        agent = Agent("bot", client=FakeClient(hit=None))
        out = agent.ask("brand new question")
        self.assertIn("similarity", out)
        self.assertEqual(out["similarity"], 0.0)

    def test_a_hit_still_reports_its_own_similarity(self):
        agent = Agent("bot", client=FakeClient(hit=_hit(0.95, similarity=0.77)))
        out = agent.ask("how do refunds work?")
        self.assertIn("similarity", out)
        self.assertEqual(out["similarity"], 0.77)

    def test_band_edges_are_inclusive(self):
        exact = Agent("bot", client=FakeClient(hit=_hit(0.85)))
        self.assertEqual(exact.ask("q")["route"], "cache")
        edge = Agent("bot", client=FakeClient(hit=_hit(0.60)))
        self.assertEqual(edge.ask("q")["route"], "cheap")

    def test_invalid_thresholds_are_refused_before_any_lookup(self):
        bad = [
            {"cheap_above": 0.9, "serve_above": 0.5},
            {"serve_above": 1.5},
            {"cheap_above": -0.1},
            {"serve_above": -0.2, "cheap_above": -0.3},
        ]
        for kwargs in bad:
            with self.subTest(**kwargs):
                client = FakeClient(hit=_hit(0.99))
                agent = Agent("bot", client=client)
                with self.assertRaises(ValueError):
                    agent.ask("q", **kwargs)
                self.assertNotIn("cget_hit", client.kinds())
                self.assertEqual(sum(agent.route_counts.values()), 0)

    def test_custom_valid_thresholds_are_accepted(self):
        agent = Agent("bot", client=FakeClient(hit=_hit(0.55)))
        self.assertEqual(agent.ask("q", serve_above=0.5, cheap_above=0.5)["route"], "cache")


class SpeakTests(unittest.TestCase):
    def test_same_voice_and_text_reuses_audio(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        calls = []

        def synth(text):
            calls.append(text)
            return b"ALLOY:" + text.encode()

        first = agent.speak("your order shipped", synth, voice="alloy")
        second = agent.speak("your order shipped", synth, voice="alloy")
        self.assertEqual(calls, ["your order shipped"])
        self.assertEqual(first, second)
        self.assertEqual((agent.audio_hits, agent.audio_misses), (1, 1))

    def test_a_different_voice_never_reuses_another_voices_audio(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        alloy_calls, nova_calls = [], []

        def alloy(text):
            alloy_calls.append(text)
            return b"ALLOY:" + text.encode()

        def nova(text):
            nova_calls.append(text)
            return b"NOVA:" + text.encode()

        spoken = agent.speak("your order shipped", alloy, voice="alloy")
        other = agent.speak("your order shipped", nova, voice="nova")
        self.assertEqual(spoken, b"ALLOY:your order shipped")
        self.assertEqual(other, b"NOVA:your order shipped")
        self.assertNotEqual(other, spoken)
        self.assertEqual(nova_calls, ["your order shipped"])
        self.assertEqual(agent.audio_hits, 0)
        self.assertEqual(agent.audio_misses, 2)

    def test_different_text_same_voice_is_not_reused(self):
        agent = Agent("bot", client=FakeClient())
        calls = []

        def synth(text):
            calls.append(text)
            return text.encode()

        agent.speak("one", synth, voice="alloy")
        agent.speak("two", synth, voice="alloy")
        self.assertEqual(calls, ["one", "two"])
        self.assertEqual(agent.audio_hits, 0)

    def test_blank_voice_is_refused_and_nothing_is_synthesised(self):
        calls = []

        def synth(text):
            calls.append(text)
            return b"audio"

        for bad in ("", "   ", None):
            with self.subTest(voice=bad):
                agent = Agent("bot", client=FakeClient())
                with self.assertRaises(ValueError):
                    agent.speak("hello", synth, voice=bad)
        self.assertEqual(calls, [])

    def test_corrupt_cached_audio_falls_back_to_fresh_synthesis(self):
        client = FakeClient()
        key = json.dumps({"voice": "alloy", "text": "hello"}, sort_keys=True)
        client.tools[("crowkis.tts", key)] = b"!!! not base64 !!!"
        agent = Agent("bot", client=client)
        calls = []

        def synth(text):
            calls.append(text)
            return b"FRESH"

        self.assertEqual(agent.speak("hello", synth, voice="alloy"), b"FRESH")
        self.assertEqual(calls, ["hello"])
        self.assertEqual(agent.audio_hits, 0)

    def test_empty_synthesis_is_never_cached(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        calls = []

        def silent(text):
            calls.append(text)
            return b""

        agent.speak("hello", silent, voice="alloy")
        agent.speak("hello", silent, voice="alloy")
        self.assertEqual(len(calls), 2)
        self.assertEqual(client.tools, {})

    def test_cached_audio_is_stored_base64_and_round_trips(self):
        client = FakeClient()
        agent = Agent("bot", client=client)
        raw = b"\x00\x01\x02binary-audio\xff"
        agent.speak("hi there", lambda _t: raw, voice="alloy")
        stored = next(iter(client.tools.values()))
        self.assertEqual(base64.b64decode(stored), raw)
        self.assertEqual(agent.speak("hi there", lambda _t: b"UNUSED", voice="alloy"), raw)


class VoiceSessionTests(unittest.TestCase):
    def _session(self, confidence=0.99, **kwargs):
        client = FakeClient(hit=_hit(confidence, response=b"we refund in 3 days"))
        agent = Agent("caller", client=client)
        kwargs.setdefault("voice", "alloy")
        return client, VoiceSession(agent, **kwargs)

    def test_empty_transcript_is_never_matched(self):
        for blank in ("", "   ", None):
            with self.subTest(said=blank):
                client, session = self._session()
                decision = session.decide(blank)
                self.assertEqual(decision.action, "infer")
                self.assertFalse(decision.served_from_cache)
                self.assertNotIn("cget_hit", client.kinds())
                self.assertEqual(session.refused_short, 1)
                self.assertEqual(session.served, 0)

    def test_too_short_transcript_is_never_matched(self):
        client, session = self._session(min_words=4)
        decision = session.decide("refund policy?")
        self.assertEqual(decision.action, "infer")
        self.assertNotIn("cget_hit", client.kinds())
        self.assertEqual(session.refused_short, 1)
        self.assertEqual(session.transcript, [])

    def test_confident_hit_is_served(self):
        client, session = self._session(confidence=0.99)
        decision = session.decide("what is the refund policy")
        self.assertEqual(decision.action, "serve")
        self.assertTrue(decision.served_from_cache)
        self.assertEqual(decision.text, "we refund in 3 days")
        self.assertIn("cget_hit", client.kinds())
        self.assertEqual(session.served, 1)
        self.assertEqual(len(session.transcript), 2)

    def test_confident_hit_is_voiced_when_a_synthesiser_is_given(self):
        client, session = self._session(confidence=0.99, synthesise=lambda t: b"WAV:" + t.encode())
        decision = session.decide("what is the refund policy")
        self.assertEqual(decision.audio, b"WAV:we refund in 3 days")

    def test_unconfident_hit_is_not_served(self):
        client, session = self._session(confidence=0.80, serve_above=0.92)
        decision = session.decide("what is the refund policy")
        self.assertEqual(decision.action, "infer")
        self.assertIsNone(decision.text)
        self.assertEqual(session.served, 0)
        self.assertEqual(session.inferred, 1)

    def test_blank_voice_is_refused(self):
        agent = Agent("caller", client=FakeClient())
        for bad in ("", "   ", None):
            with self.subTest(voice=bad):
                with self.assertRaises(ValueError):
                    VoiceSession(agent, voice=bad)

    def test_out_of_range_serve_above_is_refused(self):
        agent = Agent("caller", client=FakeClient())
        for bad in (1.5, -0.1):
            with self.subTest(serve_above=bad):
                with self.assertRaises(ValueError):
                    VoiceSession(agent, voice="alloy", serve_above=bad)

    def test_recording_a_model_turn_learns_the_answer(self):
        client, session = self._session(confidence=0.5)
        _model_turn(session, "what is the refund policy", "we refund in 3 days")
        self.assertEqual(client.entries["what is the refund policy"], "we refund in 3 days")
        self.assertEqual(len(session.injections()), 2)

    def test_blank_model_answer_is_not_learned(self):
        client, session = self._session()
        _model_turn(session, "what is the refund policy", "   ")
        self.assertEqual(client.entries, {})

    def test_serve_above_below_asks_cheap_default_still_decides(self):
        client, session = self._session(confidence=0.99, serve_above=0.5)
        decision = session.decide("what is the refund policy")
        self.assertEqual(decision.action, "serve")
        self.assertEqual(decision.text, "we refund in 3 days")
        self.assertEqual(session.served, 1)

    def test_serve_above_below_the_cheap_default_still_refuses_a_weak_hit(self):
        client, session = self._session(confidence=0.30, serve_above=0.5)
        decision = session.decide("what is the refund policy")
        self.assertEqual(decision.action, "infer")
        self.assertIsNone(decision.text)
        self.assertEqual(session.served, 0)
        self.assertEqual(session.inferred, 1)


class StatsTests(unittest.TestCase):
    def test_route_stats_add_up(self):
        agent = Agent("bot", client=FakeClient(hit=_hit(0.95)))
        agent.ask("q")
        agent._client.hit = _hit(0.70)
        agent.ask("q")
        agent._client.hit = None
        agent.ask("q")
        stats = agent.route_stats()
        self.assertEqual(stats["asked"], 3)
        self.assertEqual(stats["cache"] + stats["cheap"] + stats["expensive"], stats["asked"])
        self.assertEqual(stats["served_without_a_model_pct"], 33.33)

    def test_route_stats_are_safe_when_nothing_was_asked(self):
        stats = Agent("bot", client=FakeClient()).route_stats()
        self.assertEqual(stats["asked"], 0)
        self.assertEqual(stats["served_without_a_model_pct"], 0.0)

    def test_tool_stats_add_up(self):
        agent = Agent("bot", client=FakeClient())

        @agent.tool
        def echo(x):
            return x

        echo(1)
        echo(1)
        echo(2)
        stats = agent.tool_stats()
        self.assertEqual(stats, {"calls": 3, "cached": 1, "executed": 2, "avoided_pct": 33.33})

    def test_tool_stats_are_safe_when_no_tool_ran(self):
        self.assertEqual(
            Agent("bot", client=FakeClient()).tool_stats(),
            {"calls": 0, "cached": 0, "executed": 0, "avoided_pct": 0.0},
        )

    def test_audio_stats_add_up(self):
        agent = Agent("bot", client=FakeClient())
        agent.speak("hello there", lambda t: b"A", voice="alloy")
        agent.speak("hello there", lambda t: b"A", voice="alloy")
        stats = agent.audio_stats()
        self.assertEqual(stats["spoken"], stats["from_cache"] + stats["synthesised"])
        self.assertEqual(stats, {"spoken": 2, "from_cache": 1, "synthesised": 1, "tts_avoided_pct": 50.0})

    def test_audio_stats_are_safe_when_nothing_was_spoken(self):
        self.assertEqual(Agent("bot", client=FakeClient()).audio_stats()["tts_avoided_pct"], 0.0)

    def test_voice_session_stats_exclude_refused_turns_from_turn_count(self):
        client = FakeClient(hit=_hit(0.99, response=b"answer"))
        agent = Agent("caller", client=client)
        session = VoiceSession(agent, voice="alloy")
        session.decide("what is the refund policy")
        client.hit = _hit(0.10, response=b"answer")
        session.decide("what is the exchange policy")
        session.decide("hi")
        stats = session.stats()
        self.assertEqual(stats["turns"], stats["served_from_cache"] + stats["model_calls"])
        self.assertEqual(stats["turns"], 2)
        self.assertEqual(stats["refused_too_short"], 1)
        self.assertEqual(stats["model_calls_avoided_pct"], 50.0)

    def test_voice_session_stats_are_safe_on_an_empty_call(self):
        agent = Agent("caller", client=FakeClient())
        stats = VoiceSession(agent, voice="alloy").stats()
        self.assertEqual(stats["turns"], 0)
        self.assertEqual(stats["model_calls_avoided_pct"], 0.0)


class PersonalShapeTests(unittest.TestCase):
    def test_every_personal_utterance_is_classified_personal(self):
        for said in PERSONAL_UTTERANCES:
            with self.subTest(said=said):
                self.assertTrue(_is_personal(said))

    def test_every_general_utterance_is_classified_general(self):
        for said in GENERAL_UTTERANCES:
            with self.subTest(said=said):
                self.assertFalse(_is_personal(said))

    def test_the_fixture_covers_both_verdicts(self):
        self.assertEqual(len(PERSONAL_UTTERANCES), 20)
        self.assertEqual(len(GENERAL_UTTERANCES), 24)
        self.assertEqual(
            set(PERSONAL_UTTERANCES) & set(GENERAL_UTTERANCES), set()
        )

    def test_a_second_person_possessive_is_not_the_callers_own_record(self):
        self.assertFalse(_is_personal("what is your refund policy"))
        self.assertTrue(_is_personal("what is my refund policy"))


class ContextShapeTests(unittest.TestCase):
    def test_connectives_and_ellipsis_mark_a_turn_context_dependent(self):
        for said in (
            "and for ten people",
            "so what about the annual one",
            "what about ten people",
            "how about next week",
            "okay and for ten people",
            "for ten people",
            "with the annual discount",
            "how much is it",
        ):
            with self.subTest(said=said):
                self.assertTrue(_is_context_dependent(said))

    def test_self_contained_turns_are_left_alone(self):
        for said in (
            "what does the standard plan cost",
            "what are your opening hours",
            "when will i get my order",
            "cancel my order",
            "i lost my card and need to replace it",
        ):
            with self.subTest(said=said):
                self.assertFalse(_is_context_dependent(said))


class PrivateAnswerTests(unittest.TestCase):
    def _session(self, client, **kwargs):
        kwargs.setdefault("voice", "alloy")
        return VoiceSession(Agent("caller", client=client), **kwargs)

    def test_two_callers_share_one_template_and_keep_their_own_values(self):
        client = ScopedFakeClient()
        question = "when will i get my order"

        first = self._session(client, values={"order_id": "A-1001", "eta": "Tuesday"}, share_templates=True)
        self.assertEqual(first.decide(question).action, "infer")
        _model_turn(first, 
            question, "Your order A-1001 is due to arrive on Tuesday."
        )

        stored = client.writes[-1]
        self.assertTrue(stored["template"])
        self.assertEqual(stored["query"], question)
        self.assertEqual(
            stored["response"], "Your order {order_id} is due to arrive on {eta}."
        )
        self.assertNotIn("A-1001", stored["response"])
        self.assertNotIn("Tuesday", stored["response"])

        second = self._session(client, values={"order_id": "B-2002", "eta": "Friday"})
        decision = second.decide(question)
        self.assertEqual(decision.action, "serve")
        self.assertEqual(
            decision.text, "Your order B-2002 is due to arrive on Friday."
        )
        self.assertNotIn("A-1001", decision.text)
        self.assertNotIn("Tuesday", decision.text)
        self.assertEqual(len(client.templates), 1)
        self.assertEqual(client.shared, {})
        self.assertTrue(client.reads[-1]["template"])

    def test_a_personal_turn_with_no_values_is_refused_and_never_written(self):
        client = ScopedFakeClient()
        session = self._session(client)
        question = "when will i get my order"

        decision = session.decide(question)
        self.assertEqual(decision.action, "infer")
        self.assertIn("values", decision.reason)
        self.assertEqual(client.reads, [])

        _model_turn(session, question, "Your order A-1001 arrives on Tuesday.")
        self.assertEqual(client.writes, [])
        self.assertEqual(client.shared, {})
        self.assertEqual(client.templates, {})
        self.assertEqual(session.stats()["uncacheable_personal"], 1)

        _model_turn(session, 
            "what is the return policy", "Returns are free for 30 days."
        )
        self.assertEqual(len(client.writes), 1)
        self.assertFalse(client.writes[-1]["template"])
        self.assertEqual(
            client.shared, {"what is the return policy": "Returns are free for 30 days."}
        )
        self.assertEqual(session.stats()["uncacheable_personal"], 1)

    def test_a_general_turn_still_uses_the_shared_cache_untouched(self):
        client = ScopedFakeClient()
        client.shared["what is the return policy"] = "Returns are free for 30 days."
        session = self._session(client, values={"order_id": "A-1001"}, ttl=86400)

        decision = session.decide("what is the return policy")
        self.assertEqual(decision.action, "serve")
        self.assertEqual(decision.text, "Returns are free for 30 days.")
        self.assertEqual(
            client.reads[-1], {"query": "what is the return policy", "template": False}
        )

        _model_turn(session, "what are your opening hours", "Nine to five.")
        self.assertFalse(client.writes[-1]["template"])
        self.assertEqual(client.writes[-1]["ttl"], 86400)
        self.assertEqual(client.templates, {})

    def test_a_template_slot_this_call_cannot_fill_is_never_spoken(self):
        client = ScopedFakeClient()
        question = "when will i get my order"
        client.templates[question] = "Your order {order_id} is due to arrive on {eta}."

        blind = self._session(client, values={"order_id": "C-3003"})
        refused = blind.decide(question)
        self.assertEqual(refused.action, "infer")
        self.assertIsNone(refused.text)
        self.assertEqual(blind.served, 0)
        self.assertEqual(blind.refused_private, 1)

        ready = self._session(client, values={"order_id": "C-3003", "eta": "Monday"})
        served = ready.decide(question)
        self.assertEqual(served.action, "serve")
        self.assertEqual(
            served.text, "Your order C-3003 is due to arrive on Monday."
        )

    def test_a_value_that_survives_reverse_substitution_is_never_stored(self):
        client = ScopedFakeClient()
        question = "when will i get my order"
        values = {"order_id": "A-1001", "eta": "Tuesday"}

        leaky = self._session(client, values=dict(values), ttl=86400)
        _model_turn(leaky, question, "Your order A-1001 is due on tuesday.")
        self.assertEqual(client.writes, [])
        self.assertEqual(client.templates, {})
        self.assertEqual(client.shared, {})
        self.assertEqual(leaky.stats()["uncacheable_personal"], 1)

        clean = self._session(client, values=dict(values), ttl=86400, share_templates=True)
        _model_turn(clean, question, "Your order A-1001 is due on Tuesday.")
        shaped = client.writes[-1]
        self.assertTrue(shaped["template"])
        self.assertEqual(shaped["ttl"], 86400)
        self.assertEqual(shaped["response"], "Your order {order_id} is due on {eta}.")
        self.assertEqual(clean.stats()["uncacheable_personal"], 0)

    def test_a_personal_answer_with_no_declared_values_never_becomes_a_template(self):
        client = ScopedFakeClient()
        session = self._session(client)
        _model_turn(session, 
            "when will i get my order", "Your order arrives on Tuesday."
        )
        self.assertEqual(client.writes, [])
        self.assertEqual(client.templates, {})
        self.assertEqual(client.shared, {})
        self.assertEqual(session.stats()["uncacheable_personal"], 1)

    def test_values_filled_mid_call_unlock_the_template_path(self):
        client = ScopedFakeClient()
        question = "when will i get my order"
        session = self._session(client, share_templates=True)
        self.assertEqual(session.decide(question).action, "infer")

        session.set_values(order_id="D-4004", eta="Thursday")
        _model_turn(session, 
            question, "Your order D-4004 is due to arrive on Thursday."
        )
        self.assertTrue(client.writes[-1]["template"])
        self.assertEqual(
            client.writes[-1]["response"],
            "Your order {order_id} is due to arrive on {eta}.",
        )
        self.assertEqual(session.stats()["uncacheable_personal"], 0)


class ContextKeyTests(unittest.TestCase):
    def _session(self, client):
        return VoiceSession(Agent("caller", client=client), voice="alloy")

    def test_the_same_follow_up_in_two_contexts_gets_two_different_answers(self):
        client = ScopedFakeClient()
        follow_up = "and for ten people"

        priced = self._session(client)
        _model_turn(priced, 
            "what does the standard plan cost", "The standard plan is 20 a month."
        )
        _model_turn(priced, follow_up, "Ten seats cost 180 a month.")

        booked = self._session(client)
        _model_turn(booked, 
            "what does a meeting room cost", "A meeting room is 40 an hour."
        )
        _model_turn(booked, follow_up, "A room for ten is 60 an hour.")

        self.assertEqual(len(client.shared), 4)

        replay_priced = self._session(client)
        replay_priced.decide("what does the standard plan cost")
        priced_again = replay_priced.decide(follow_up)

        replay_booked = self._session(client)
        replay_booked.decide("what does a meeting room cost")
        booked_again = replay_booked.decide(follow_up)

        self.assertEqual(priced_again.action, "serve")
        self.assertEqual(booked_again.action, "serve")
        self.assertEqual(priced_again.text, "Ten seats cost 180 a month.")
        self.assertEqual(booked_again.text, "A room for ten is 60 an hour.")
        self.assertNotEqual(priced_again.text, booked_again.text)

    def test_a_self_contained_utterance_is_never_context_prefixed(self):
        client = ScopedFakeClient()
        session = self._session(client)
        _model_turn(session, 
            "what does the standard plan cost", "The standard plan is 20 a month."
        )
        _model_turn(session, 
            "what are your opening hours", "We are open nine to five."
        )
        keys = [write["query"] for write in client.writes]
        self.assertEqual(
            keys, ["what does the standard plan cost", "what are your opening hours"]
        )
        self.assertNotIn("||", keys[1])

        _model_turn(session, "and for ten people", "Groups of ten are welcome during opening hours.")
        self.assertEqual(
            client.writes[-1]["query"],
            "what are your opening hours || and for ten people",
        )

    def test_a_follow_up_with_no_prior_turn_cannot_be_resolved(self):
        client = ScopedFakeClient()
        session = self._session(client)
        decision = session.decide("and for ten people")
        self.assertEqual(decision.action, "infer")
        self.assertIn("earlier turn", decision.reason)
        self.assertEqual(client.reads, [])

        _model_turn(session, "and for ten people", "Ten seats cost 180.")
        self.assertEqual(client.writes, [])


if __name__ == "__main__":
    unittest.main()


class SlotSafetyTests(unittest.TestCase):
    def test_a_short_value_never_splits_a_number(self):
        from crowkis.voice import _abstract
        self.assertEqual(_abstract("within 24 hours", {"count": "2"}), "within 24 hours")

    def test_a_value_is_replaced_only_as_a_whole_word(self):
        from crowkis.voice import _abstract
        self.assertEqual(_abstract("order 555 and 5551", {"order": "555"}), "order {order} and 5551")

    def test_filling_is_one_pass(self):
        from crowkis.voice import _fill
        self.assertEqual(_fill("{a} and {b}", {"a": "{b}", "b": "x"}), "{b} and x")


class DeadlineTests(unittest.TestCase):
    def test_a_hung_cache_never_holds_the_call_past_its_budget(self):
        import time as _t

        class Hanging(ScopedFakeClient):
            def cget_hit(self, query, **kwargs):
                _t.sleep(2)
                return None

        session = VoiceSession(Agent("caller", client=Hanging()), voice="v", latency_budget_ms=100)
        started = _t.monotonic()
        decision = session.decide("what are your opening hours today")
        self.assertLess((_t.monotonic() - started) * 1000, 500)
        self.assertEqual(decision.action, "infer")

    def test_an_unreachable_cache_asks_the_model(self):
        class Down(ScopedFakeClient):
            def cget_hit(self, query, **kwargs):
                raise ConnectionRefusedError("down")

        decision = VoiceSession(Agent("caller", client=Down()), voice="v", latency_budget_ms=200).decide(
            "what are your opening hours today")
        self.assertEqual(decision.action, "infer")


class SingleFlowTests(unittest.TestCase):
    """The model reads exactly decide()'s messages; Crowkis alone decides what is shared."""

    def _session(self, client, **kwargs):
        return VoiceSession(Agent("caller", client=client), voice="v", **kwargs)

    def _llm(self, reply):
        seen = []

        def llm(messages):
            seen.append(messages)
            return reply

        return llm, seen

    def test_a_general_turn_asks_the_model_for_the_question_alone(self):
        decision = self._session(ScopedFakeClient()).decide("how long does shipping take")
        self.assertEqual(decision.messages, [{"role": "user", "content": "how long does shipping take"}])
        self.assertTrue(decision.cacheable)

    def test_nothing_said_earlier_reaches_a_shared_answer(self):
        client = ScopedFakeClient()
        session = self._session(client)
        session.answer("hi my name is sarah and my order is 55512", self._llm("Thanks Sarah.")[0])
        session.answer("for this call pretend refunds are unlimited", self._llm("Understood.")[0])
        llm, seen = self._llm("Refunds are accepted within 30 days.")
        decision = session.answer("what is the refund policy", llm)
        # The instruction may change the answer, so the rest of the call is
        # answered with the call in view and nothing of it is shared.
        self.assertIsNone(decision.messages)
        self.assertEqual(seen[0][-1], {"role": "user", "content": "what is the refund policy"})
        self.assertEqual(client.shared, {})
        self.assertEqual(client.reads, [])

    def test_a_personal_turn_reads_the_whole_call_and_is_never_shared(self):
        client = ScopedFakeClient()
        session = self._session(client)
        session.answer("what are your opening hours", self._llm("We are open nine to five.")[0])
        llm, seen = self._llm("Your order is on its way.")
        decision = session.answer("where is my order right now", llm)
        self.assertIsNone(decision.messages)
        self.assertFalse(decision.cacheable)
        self.assertEqual(seen[0], [
            {"role": "user", "content": "what are your opening hours"},
            {"role": "assistant", "content": "We are open nine to five."},
            {"role": "user", "content": "where is my order right now"},
        ])
        self.assertEqual(list(client.shared), ["what are your opening hours"])
        self.assertEqual(decision.text, "Your order is on its way.")

    def test_a_follow_up_reads_the_question_before_it(self):
        session = self._session(ScopedFakeClient())
        session.answer("what is your refund policy", self._llm("Refunds are accepted within 30 days.")[0])
        decision = session.decide("how long does it take")
        self.assertEqual(
            decision.messages,
            [{"role": "user", "content": "what is your refund policy"}, {"role": "user", "content": "how long does it take"}],
        )
        self.assertTrue(decision.cacheable)

    def test_a_follow_up_to_a_personal_turn_is_never_shared(self):
        client = ScopedFakeClient()
        session = self._session(client)
        session.answer("where is my order right now", self._llm("It ships today.")[0])
        llm, seen = self._llm("Usually two days.")
        decision = session.answer("how long does it take", llm)
        self.assertFalse(decision.cacheable)
        self.assertEqual(len(seen[0]), 3)
        self.assertEqual(client.shared, {})
        self.assertEqual(session.stats()["not_shareable"], 1)

    def test_the_system_prompt_goes_first(self):
        llm, seen = self._llm("We are open nine to five.")
        self._session(ScopedFakeClient()).answer("what are your opening hours", llm, system="You are a store agent.")
        self.assertEqual(seen[0], [
            {"role": "system", "content": "You are a store agent."},
            {"role": "user", "content": "what are your opening hours"},
        ])

    def test_a_cached_answer_never_calls_the_model(self):
        client = ScopedFakeClient()
        client.shared["what are your opening hours"] = "Nine to five."
        llm, seen = self._llm("unused")
        decision = self._session(client).answer("what are your opening hours", llm)
        self.assertEqual(decision.action, "serve")
        self.assertEqual(decision.text, "Nine to five.")
        self.assertEqual(seen, [])

    def test_a_realtime_model_turn_is_kept_to_the_call(self):
        client = ScopedFakeClient()
        session = self._session(client)
        session.decide("what are your opening hours")
        session.record_private_turn("what are your opening hours", "Nine to five.")
        self.assertEqual(client.shared, {})
        self.assertEqual(session.stats()["not_shareable"], 1)
        self.assertEqual(len(session.injections()), 2)

    def test_an_answer_with_no_decision_behind_it_is_never_shared(self):
        client = ScopedFakeClient()
        session = self._session(client)
        session._record_model_turn("what are your opening hours", "Nine to five.")
        self.assertEqual(client.shared, {})
        self.assertEqual(len(session.injections()), 2)

    def test_an_answer_carrying_a_declared_value_is_never_shared(self):
        client = ScopedFakeClient()
        session = self._session(client, values={"order_id": "A-1001"})
        session.answer("what are your opening hours", self._llm("Nine to five, and order A-1001 ships today.")[0])
        self.assertEqual(client.shared, {})
        self.assertEqual(session.stats()["not_shareable"], 1)

    def test_a_refused_write_never_raises_into_the_call(self):
        class Refusing(ScopedFakeClient):
            def cset(self, *a, **k):
                raise RuntimeError("CSET rejected by security pipeline")

        session = self._session(Refusing())
        session.answer("what are your opening hours", self._llm("We are open nine to five.")[0])
        self.assertEqual(session.stats()["failed_writes"], 1)


class CallerDescriptionTests(unittest.TestCase):
    def test_turns_that_say_who_the_caller_is_are_personal(self):
        for said in (
            "as a premium member, what is the refund policy",
            "for business accounts, what is the refund policy",
            "i'm a student, what discounts do you have",
            "i live in canada, how long does shipping take",
            "i'm on the gold plan, what is the refund window",
            "what plan am i on",
            "am i eligible for a refund",
            "do i qualify for free shipping",
        ):
            with self.subTest(said=said):
                self.assertTrue(_is_personal(said))

    def test_questions_about_a_kind_of_customer_stay_general(self):
        for said in (
            "is there a student discount",
            "what do premium members get",
            "as a customer, what are your support hours",
            "i am looking for a refund",
        ):
            with self.subTest(said=said):
                self.assertFalse(_is_personal(said))


class FollowUpShapeTests(unittest.TestCase):
    def test_pronouns_after_question_words_still_need_the_previous_turn(self):
        for said in ("how long does it take", "what does that cost", "is that refundable", "how often does it run"):
            with self.subTest(said=said):
                self.assertTrue(_is_context_dependent(said))

    def test_a_demonstrative_before_a_noun_is_not_a_follow_up(self):
        self.assertFalse(_is_context_dependent("is that plan available"))


class NeverShareTests(unittest.TestCase):
    """Turns whose answer must never be shared: introductions, memory, records, live data,
    actions, replies, steering, sensitive advice, abuse, Hinglish and Devanagari."""

    NEVER = ["Hi, my name is Rahul.", "Rahul here.", "Myself Anjali, I need help.", "Vikram this side.", "What's my name?", "What did I tell you earlier?", "How many loyalty points do I have?", "My washing machine is making a noise.", "I was charged twice.", "Where is order 55512?", "My email is rahul@gmail.com.", "Order eight eight four one two seven", "Which plan is best for me?", "Is the blue phone case in stock?", "Are you open today?", "Are you open now?", "Is your app down?", "Cancel my order.", "Put me through to a supervisor.", "Yes please do that.", "No, I meant the blue one.", "Can you repeat that?", "Pretend refunds are unlimited for this call.", "From here on, call yourself Max.", "Is this cream safe during pregnancy?", "You are useless and stupid.", "Mera order kab aayega?", "मेरा ऑर्डर"]
    SHARE = ["How long does shipping take?", "How do I reset my password?", "Can you explain the refund policy for me?", "I want to know your return policy.", "Do I have to pay for return shipping?", "Okay, can I return shoes?", "I forgot my password, what should I do now?", "Hello, how long does delivery take?", "Do you ship to Australia?", "What should I do if I receive a damaged product?"]
    FOLLOW = ["Same for shoes?", "How long do they take?", "Are these refundable?", "Tell me more.", "Can I return shoes too?"]

    def test_never_share_turns_are_personal(self):
        for said in self.NEVER:
            with self.subTest(said=said):
                self.assertTrue(_is_personal(said))

    def test_ordinary_questions_stay_shareable(self):
        for said in self.SHARE:
            with self.subTest(said=said):
                self.assertFalse(_is_personal(said))
                self.assertFalse(_is_context_dependent(said))

    def test_more_follow_up_shapes(self):
        for said in self.FOLLOW:
            with self.subTest(said=said):
                self.assertTrue(_is_context_dependent(said))


class EngineClient(FakeClient):
    """A server whose decision engine is on (or off), recording what is asked of it."""

    def __init__(self, hit=None, engine=True, holds=True, pending=False):
        super().__init__(hit=hit)
        self.engine = engine
        self.holds = holds
        self.pending = pending

    def cget_hit(self, query, **kwargs):
        self.calls.append(("cget_hit", query, kwargs.get("threshold")))
        return self.hit

    def cdecision(self, query, *, tenant=None):
        self.calls.append(("cdecision", query, tenant))
        if self.engine is None:
            raise ConnectionError("unknown command 'CDECISION'")
        return {
            "engine": self.engine,
            "holds": bool(self.engine and self.holds),
            "cached": self.pending,
            "judged": False,
            "pending": self.pending,
        }

    def cnotice_add(self, text, *, lasts=None, preview=False, tenant=None):
        self.calls.append(("cnotice_add", text, lasts, preview, tenant))
        return {"id": "abc", "removed": 2}


def _judged(similarity=0.99, response=b"You are welcome.", **flags):
    return CacheHit(
        response=response,
        similarity=similarity,
        ttl_remaining=600,
        matched_key=b"k",
        confidence=0.99,
        hit_type="exact" if similarity >= 1.0 else "semantic",
        judged=True,
        **flags,
    )


class ShortTurnTests(unittest.TestCase):
    def _session(self, hit, engine=True, short_turns=True):
        client = EngineClient(hit=hit, engine=engine)
        return client, VoiceSession(Agent("caller", client=client), voice="alloy", short_turns=short_turns)

    def test_short_turns_are_off_unless_asked_for(self):
        client, session = self._session(_judged(similarity=1.0, vouched=True), short_turns=False)
        self.assertEqual(session.decide("thank you").action, "infer")
        self.assertEqual(client.calls, [], "neither looked up nor asked about")
        self.assertEqual(session.refused_short, 1)

    def test_a_short_turn_the_engine_vouched_for_is_served_on_an_exact_match_only(self):
        client, session = self._session(_judged(similarity=1.0, vouched=True))
        decision = session.decide("thank you")
        self.assertEqual((decision.action, decision.text), ("serve", "You are welcome."))
        lookups = [call for call in client.calls if call[0] == "cget_hit"]
        self.assertEqual(lookups, [("cget_hit", "thank you", 0.995)], "a short turn never matches on meaning")
        self.assertEqual((session.served, session.refused_short), (1, 0))

    def test_a_short_turn_nobody_vouched_for_goes_to_the_model(self):
        # Cached and confident, but not vouched for, or not the same question.
        for hit in (_hit(0.99, similarity=1.0), _judged(similarity=1.0), _judged(similarity=0.999, vouched=True)):
            with self.subTest(judged=hit.judged, similarity=hit.similarity):
                _, session = self._session(hit)
                decision = session.decide("thank you")
                self.assertEqual(decision.action, "infer")
                self.assertIn("stand on its own", decision.reason)
                self.assertEqual(session.served, 0)

    def test_without_an_engine_a_short_turn_is_not_even_looked_up(self):
        for engine in (False, None):
            with self.subTest(engine=engine):
                client, session = self._session(_judged(similarity=1.0, vouched=True), engine=engine)
                self.assertEqual(session.decide("thank you").action, "infer")
                self.assertNotIn("cget_hit", client.kinds())
                self.assertEqual(session.refused_short, 1)

    def test_the_server_is_asked_once_whether_it_judges_answers(self):
        client, session = self._session(_judged(similarity=1.0, vouched=True))
        for _ in range(5):
            session.decide("thank you")
        again = VoiceSession(session.agent, voice="alloy", short_turns=True)
        again.decide("hello there")
        self.assertEqual(client.kinds().count("cdecision"), 1)

    def test_a_long_turn_never_asks(self):
        client, session = self._session(_hit(0.99))
        session.decide("what is the refund policy")
        self.assertNotIn("cdecision", client.kinds())


class CommitmentTests(unittest.TestCase):
    QUESTION = "how much is the pro plan"

    def _decide(self, hit, **kwargs):
        client = EngineClient(hit=hit)
        session = VoiceSession(Agent("caller", client=client), voice="alloy", **kwargs)
        return session, session.decide(self.QUESTION)

    def test_by_default_a_commitment_is_spoken_only_on_an_exact_match(self):
        near = _judged(similarity=0.97, lifetime="operational", commitment=True)
        exact = _judged(similarity=1.0, lifetime="operational", commitment=True)
        session, decision = self._decide(near)
        self.assertEqual(decision.action, "infer")
        self.assertIn("commitment", decision.reason)
        self.assertEqual(session.stats()["commitments_sent_to_model"], 1)
        self.assertEqual(self._decide(exact)[1].action, "serve")

    def test_an_ordinary_answer_is_unaffected(self):
        ordinary = _judged(similarity=0.97, lifetime="slow")
        for mode in ("serve", "exact", "never"):
            with self.subTest(mode=mode):
                self.assertEqual(self._decide(ordinary, commitments=mode)[1].action, "serve")

    def test_each_mode_does_what_it_says(self):
        same_score = CacheHit(
            response=b"x", similarity=1.0, ttl_remaining=600, matched_key=b"k", confidence=0.99,
            hit_type="vector", judged=True, commitment=True,
        )
        hits = {
            "near": _judged(similarity=0.97, commitment=True),
            "exact": _judged(similarity=1.0, commitment=True),
            # Another question can score a similarity of exactly 1; it is still another question.
            "same-score": same_score,
        }
        served = {
            "serve": {"near", "exact", "same-score"},
            "exact": {"exact"},
            "never": set(),
        }
        for mode, expected in served.items():
            for name, hit in hits.items():
                with self.subTest(mode=mode, hit=name):
                    action = self._decide(hit, commitments=mode)[1].action
                    self.assertEqual(action == "serve", name in expected)

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            VoiceSession(Agent("caller", client=EngineClient()), voice="alloy", commitments="maybe")


class SpeakableTests(unittest.TestCase):
    def test_text_written_for_a_screen_is_not_spoken(self):
        from crowkis.voice import _speakable

        for text in (
            "See https://example.com/refunds for details.",
            "Visit www.example.com.",
            "Run `pip install crowkis` first.",
            "Read the [refund policy](/refunds).",
            "Refunds take **three days**.",
            "# Refunds\nThree days.",
            "| plan | price |\n| pro | 20 |",
        ):
            with self.subTest(text=text):
                self.assertFalse(_speakable(text))
        for text in (
            "Refunds take three days.",
            "It costs 20 dollars, or 15 if you pay yearly.",
            "Press 1 for sales - or stay on the line.",
            "Our number-one plan is Pro.",
        ):
            with self.subTest(text=text):
                self.assertTrue(_speakable(text))

    def test_an_unspeakable_hit_goes_to_the_model(self):
        client = EngineClient(hit=_hit(0.99, response=b"See https://example.com/refunds"))
        session = VoiceSession(Agent("caller", client=client), voice="alloy")
        decision = session.decide("what is the refund policy")
        self.assertEqual(decision.action, "infer")
        self.assertEqual(session.stats()["unspeakable_answers"], 1)


class WarmStartTests(unittest.TestCase):
    def test_past_calls_fill_the_cache_under_the_live_rules(self):
        from crowkis.voice import warm_from_calls

        with self.assertRaises(RuntimeError, msg="nothing checks a transcript without the engine"):
            warm_from_calls(Agent("caller", client=FakeClient()), [[("Do you deliver?", "Yes.")]])
        with self.assertRaises(RuntimeError):
            warm_from_calls(Agent("caller", client=EngineClient(engine=False)), [[("Do you deliver?", "Yes.")]])
        with self.assertRaises(RuntimeError, msg="an engine that serves before it judges checks nothing in time"):
            warm_from_calls(Agent("caller", client=EngineClient(holds=False)), [[("Do you deliver?", "Yes.")]])

        client = EngineClient()
        calls = [
            [
                ("What are your opening hours?", "We are open eight until eight."),
                ("Hi, my name is Sarah and my order is 55512.", "Thanks Sarah, I can see order 55512."),
                ("What is the delivery time?", "Sarah, your order arrives on Tuesday."),
            ],
            [("Do you deliver on Sundays?", "Yes, between ten and four.")],
        ]
        totals = warm_from_calls(Agent("caller", client=client), calls)
        stored = {call[1]: call[2] for call in client.calls if call[0] == "cset"}
        self.assertIn("What are your opening hours?", stored)
        self.assertIn("Do you deliver on Sundays?", stored)
        self.assertNotIn("What is the delivery time?", stored, "an answer naming the caller is never shared")
        self.assertEqual((totals["calls"], totals["turns"]), (2, 4))
        self.assertGreaterEqual(totals["kept_private"], 1)
        self.assertFalse(totals["stalled"])
        self.assertNotIn("ctoolset", client.kinds(), "nothing is synthesised")
        # It waits on the question each answer was stored under.
        asked = [call[1] for call in client.calls if call[0] == "cdecision"]
        self.assertIn("Do you deliver on Sundays?", asked)

    def test_an_engine_that_is_not_keeping_up_stops_the_load_instead_of_spinning(self):
        from crowkis.voice import warm_from_calls

        client = EngineClient(pending=True)
        calls = [[(f"Do you deliver on day {n}?", "Yes, between ten and four.")] for n in range(6)]
        totals = warm_from_calls(Agent("caller", client=client), calls, wait=0.05)
        self.assertTrue(totals["stalled"])
        self.assertEqual(totals["calls"], 3, "three calls in a row were not judged in time")

    def test_a_lookup_that_fails_does_not_end_the_load(self):
        from crowkis.voice import warm_from_calls

        class Flaky(EngineClient):
            def cdecision(self, query, *, tenant=None):
                if query != "ping":
                    return None if "Sundays" in query else (_ for _ in ()).throw(ConnectionError("down"))
                return super().cdecision(query, tenant=tenant)

        calls = [[("Do you deliver on Sundays?", "Yes, between ten and four.")], [("Do you gift wrap?", "Yes, for free.")]]
        totals = warm_from_calls(Agent("caller", client=Flaky()), calls, wait=0.05)
        self.assertEqual((totals["calls"], totals["stalled"]), (2, False))


class ExplainAndAnnounceTests(unittest.TestCase):
    def test_both_are_one_call_scoped_to_the_agents_tenant(self):
        client = EngineClient()
        agent = Agent("caller", client=client, tenant="acme")
        self.assertEqual(agent.announce("we close at 3pm today", lasts=3600)["removed"], 2)
        self.assertTrue(agent.explain("what time do you close")["engine"])
        self.assertIn(("cnotice_add", "we close at 3pm today", 3600, False, "acme"), client.calls)
        self.assertIn(("cdecision", "what time do you close", "acme"), client.calls)

    def test_ask_reports_what_the_engine_recorded(self):
        hit = _judged(similarity=1.0, lifetime="operational", commitment=True, vouched=True)
        answer = Agent("caller", client=EngineClient(hit=hit)).ask("how much is the pro plan")
        self.assertEqual(
            (answer["lifetime"], answer["commitment"], answer["vouched"], answer["exact"]),
            ("operational", True, True, True),
        )
        miss = Agent("caller", client=EngineClient()).ask("how much is the pro plan")
        self.assertEqual((miss["lifetime"], miss["commitment"], miss["vouched"], miss["exact"]), (None, False, False, False))

    def test_a_hit_from_a_server_without_an_engine_parses_as_not_judged(self):
        from crowkis.client import _cache_hit, _plain

        old = _cache_hit({"response": b"a", "similarity": 1.0, "ttl": 5, "key": b"k", "confidence": 0.9, "hit_type": b"exact"})
        self.assertEqual((old.judged, old.lifetime, old.commitment, old.vouched), (False, None, False, False))
        new = _cache_hit({"response": b"a", "judged": True, "lifetime": b"slow", "commitment": True, "vouched": True})
        self.assertEqual((new.judged, new.lifetime, new.commitment, new.vouched), (True, "slow", True, True))
        self.assertEqual(_plain({b"id": b"abc", "n": 2, "all": [b"x", {"k": b"v"}]}), {"id": "abc", "n": 2, "all": ["x", {"k": "v"}]})


class EngineCheckTests(unittest.TestCase):
    def test_a_server_that_could_not_be_reached_is_asked_again(self):
        class Flaky(EngineClient):
            def cdecision(self, query, *, tenant=None):
                self.calls.append(("cdecision", query, tenant))
                if self.kinds().count("cdecision") == 1:
                    raise ConnectionError("connection closed")
                return {"engine": True}

        client = Flaky(hit=_judged(similarity=1.0, vouched=True))
        session = VoiceSession(Agent("caller", client=client), voice="alloy", short_turns=True)
        self.assertEqual(session.decide("thank you").action, "infer", "no engine is the safe reading of a failure")
        self.assertEqual(session.decide("thank you").action, "serve", "one failure must not switch short turns off for good")
        session.decide("thank you")
        self.assertEqual(client.kinds().count("cdecision"), 2, "a real answer is remembered")

    def test_an_older_server_is_asked_once(self):
        client = EngineClient(hit=_judged(similarity=1.0, vouched=True), engine=None)
        session = VoiceSession(Agent("caller", client=client), voice="alloy", short_turns=True)
        for _ in range(3):
            self.assertEqual(session.decide("thank you").action, "infer")
        self.assertEqual(client.kinds().count("cdecision"), 1)

    def test_the_engine_check_never_holds_a_call_past_its_budget(self):
        import time as _t

        class Slow(EngineClient):
            def cdecision(self, query, *, tenant=None):
                _t.sleep(0.6)
                return {"engine": True}

        client = Slow(hit=_judged(similarity=1.0, vouched=True))
        session = VoiceSession(Agent("caller", client=client), voice="alloy", latency_budget_ms=50, short_turns=True)
        started = _t.monotonic()
        decision = session.decide("thank you")
        self.assertLess((_t.monotonic() - started) * 1000, 400)
        self.assertEqual(decision.action, "infer")
        _t.sleep(0.8)
        self.assertEqual(session.decide("thank you").action, "serve", "the late answer is there for the next turn")

    def test_a_link_in_capitals_is_still_a_link(self):
        from crowkis.voice import _speakable

        self.assertFalse(_speakable("See HTTPS://EXAMPLE.COM/refunds"))
        self.assertFalse(_speakable("Visit WWW.EXAMPLE.COM"))

    def test_a_client_that_fails_softly_reads_as_no_engine_and_is_asked_again(self):
        class Soft(EngineClient):
            def cdecision(self, query, *, tenant=None):
                self.calls.append(("cdecision", query, tenant))
                return None if self.kinds().count("cdecision") == 1 else {"engine": True}

        agent = Agent("caller", client=Soft())
        self.assertFalse(agent.decides())
        self.assertTrue(agent.decides(), "a soft failure is not an answer")

    def test_a_no_is_asked_again_after_a_while_so_an_engine_switched_on_later_is_noticed(self):
        client = EngineClient(engine=False)
        agent = Agent("caller", client=client)
        self.assertFalse(agent.decides())
        client.engine = True
        self.assertFalse(agent.decides(), "not on every turn")
        agent._decides_asked -= 301
        self.assertTrue(agent.decides())


class RecordOutcomeTests(unittest.TestCase):
    """_record_model_turn says what happened to the answer, so an app can show it."""

    def _session(self, client=None, **kwargs):
        kwargs.setdefault("voice", "alloy")
        return VoiceSession(Agent("caller", client=client or ScopedFakeClient()), **kwargs)

    def test_a_shareable_answer_is_saved(self):
        session = self._session()
        session.decide("what is the refund policy")
        self.assertEqual(session._record_model_turn("what is the refund policy", "We refund in 3 days."), "saved")

    def test_an_answer_written_from_the_whole_call_is_kept(self):
        # No decide() said the answer may be shared, as when the model read the whole call.
        session = self._session()
        self.assertEqual(session._record_model_turn("what is the refund policy", "We refund in 3 days."), "kept")

    def test_a_blank_answer_is_a_non_answer(self):
        session = self._session()
        session.decide("what is the refund policy")
        self.assertEqual(session._record_model_turn("what is the refund policy", "   "), "non_answer")

    def test_a_cancelled_turn_is_interrupted(self):
        session = self._session()
        session.decide("what is the refund policy")
        session.cancel()
        self.assertEqual(session._record_model_turn("what is the refund policy", "We refund in 3 days."), "interrupted")

    def test_a_personal_answer_with_values_is_saved_as_a_template(self):
        session = self._session(values={"order_id": "A-1001", "eta": "Tuesday"}, share_templates=True)
        session.decide("when will i get my order")
        outcome = session._record_model_turn("when will i get my order", "Your order A-1001 arrives on Tuesday.")
        self.assertEqual(outcome, "template")

    def test_a_personal_answer_that_cannot_be_made_generic_is_private(self):
        session = self._session()
        session.decide("when will i get my order")
        self.assertEqual(session._record_model_turn("when will i get my order", "It arrives on Tuesday."), "private")

    def test_an_answer_repeating_this_callers_details_is_private(self):
        session = self._session(values={"name": "Sarah"})
        session.decide("what is the refund policy")
        outcome = session._record_model_turn("what is the refund policy", "Sarah, we refund in 3 days.")
        self.assertEqual(outcome, "private")

    def test_a_failed_write_is_refused(self):
        class Refusing(ScopedFakeClient):
            def cset(self, *args, **kwargs):
                raise RuntimeError("rejected by security pipeline")

        session = self._session(Refusing())
        session.decide("what is the refund policy")
        self.assertEqual(session._record_model_turn("what is the refund policy", "We refund in 3 days."), "refused")
        self.assertEqual(session.learn_errors, 1)
