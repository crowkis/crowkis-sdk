"""Agent and VoiceSession behaviour that only the retired e2e scripts used to check
(T7, T8, T9 in sdk-docs/open-items.md, 2026-10-21). Node twins: test-agent-feature-gaps.js."""
import unittest

import crowkis
from crowkis import Agent

from conformance import ConformanceStore


class MemoryStore:
    """Agent memory as the server keeps it: facts per (tenant, agent); a query returns the
    facts sharing a word with it."""

    def __init__(self):
        self.facts = {}

    def cmemset(self, agent, fact, *, ex=None, tenant=None, **_):
        self.facts.setdefault((tenant, agent), []).append(fact)
        return True

    def cmemget(self, agent, query, *, tenant=None, **_):
        words = set(query.lower().split())
        return [f for f in self.facts.get((tenant, agent), []) if words & set(f.lower().split())]


class MemorySharingTests(unittest.TestCase):  # T7
    def test_an_agent_reads_what_it_remembered(self):
        store = MemoryStore()
        Agent("support", client=store, tenant="acme").remember("the customer prefers email")
        rebuilt = Agent("support", client=store, tenant="acme")  # a new object, the same agent
        self.assertEqual(rebuilt.recall("email"), ["the customer prefers email"])

    def test_another_agent_reads_it_only_when_shared_with(self):
        store = MemoryStore()
        Agent("billing", client=store, tenant="acme").remember("invoices go out on the 1st")
        self.assertEqual(Agent("support", client=store, tenant="acme").recall("invoices"), [])
        sharing = Agent("support", client=store, tenant="acme", shares_with=["billing", "  "])
        self.assertEqual(sharing.recall("invoices"), ["invoices go out on the 1st"])
        self.assertEqual(sharing.recall("invoices", include_shared=False), [])

    def test_must_still_work_another_tenant_never_sees_it(self):
        store = MemoryStore()
        Agent("support", client=store, tenant="acme").remember("the customer prefers email")
        self.assertEqual(Agent("support", client=store, tenant="orion", shares_with=["support"]).recall("email"), [])


class ToolStore:
    def __init__(self):
        self.tools = {}

    def ctoolget(self, tool, key, *, tenant=None):
        return self.tools.get((tool, key))

    def ctoolset(self, tool, key, value, *, ex=None, tenant=None):
        self.tools[(tool, key)] = value


class ToolKeywordTests(unittest.TestCase):  # T8
    def test_a_changed_keyword_argument_runs_the_tool_again(self):
        agent = Agent("bot", client=ToolStore())
        runs = []

        @agent.tool
        def quote(item, *, express=False):
            runs.append((item, express))
            return {"item": item, "express": express}

        quote("lamp", express=False)
        quote("lamp", express=False)
        self.assertEqual(runs, [("lamp", False)], "the same keyword arguments: served from the cache")
        self.assertEqual(quote("lamp", express=True), {"item": "lamp", "express": True})
        self.assertEqual(runs, [("lamp", False), ("lamp", True)])


def _session(**options):
    return crowkis.voice_session(client=ConformanceStore(seed={"what is the return policy": "Returns are free for 30 days."}),
                                 **options)


class VoiceDetailTests(unittest.TestCase):  # T9; Node: test-voice.js and test-agent-feature-gaps.js
    def test_registered_fillers_are_normalised(self):
        session = _session()
        session.register_fillers({"  One Moment!  ": "Sure, one moment."})
        decision = session.decide("one moment")
        self.assertEqual((decision.action, decision.text), ("filler", "Sure, one moment."))

    def test_a_filler_trigger_inside_a_longer_sentence_is_not_a_filler(self):
        session = _session(fillers={"one moment": "Sure, one moment."})
        self.assertNotEqual(session.decide("one moment, what is the return policy").action, "filler")

    def test_a_lookup_past_the_budget_is_counted(self):
        session = _session(latency_budget_ms=0.000001)
        self.assertEqual(session.decide("what is the return policy").action, "infer")
        self.assertEqual(session.stats()["missed_latency_budget"], 1)

    def test_a_zero_latency_budget_is_refused(self):
        with self.assertRaises(ValueError):
            _session(latency_budget_ms=0)

    def test_cancel_is_true_once_then_false(self):
        session = _session()
        session.decide("what is the return policy")
        self.assertTrue(session.cancel())
        self.assertFalse(session.cancel())

    def test_filler_and_cache_hits_are_counted_apart(self):
        session = _session(fillers={"hello": "Hi! How can I help?"})
        session.decide("hello")
        session.decide("what is the return policy")
        stats = session.stats()
        self.assertEqual((stats["filler_hit_pct"], stats["cache_hit_pct"]), (50.0, 50.0))


if __name__ == "__main__":
    unittest.main()
