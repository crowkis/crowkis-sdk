"""SEGMENT (what besides the question changes the answer: reply language, region,
knowledge version) is sent exactly when it is set, so every existing call sends the
same frame as before."""
import unittest

from crowkis import Agent

from test_sdk import _scripted

SEGMENT = "kb=3;lang=hi;region=in;channel=chat"


class SegmentFrameTests(unittest.TestCase):
    def test_cset_cget_cget_hit_and_cstale_send_it_when_set(self):
        client, sent = _scripted([None, None, None, None], tenant="acme")
        client.cset("q", "a", segment=SEGMENT)
        client.cget("q", segment=SEGMENT)
        client.cget_hit("q", segment=SEGMENT)
        client.cstale("q", segment=SEGMENT)
        self.assertEqual(sent, [
            ["CSET", "q", "a", "TENANT", "acme", "SEGMENT", SEGMENT],
            ["CGET", "q", "TENANT", "acme", "SEGMENT", SEGMENT],
            ["CGET", "q", "TENANT", "acme", "SEGMENT", SEGMENT],
            ["CSTALE", "q", "TENANT", "acme", "SEGMENT", SEGMENT],
        ])

    def test_frames_are_unchanged_without_it(self):
        client, sent = _scripted([None, None, None, None], tenant="acme")
        client.cset("q", "a")
        client.cget("q")
        client.cget_hit("q")
        client.cstale("q")
        for frame in sent:
            self.assertNotIn("SEGMENT", frame)

    def test_the_agent_passes_it_only_when_set(self):
        client, sent = _scripted([None, None, None, None], tenant="acme")
        agent = Agent("bot", client=client)
        agent.ask("q", segment=SEGMENT)
        agent.learn("q", "a", segment=SEGMENT)
        agent.ask("q")
        agent.learn("q", "a")
        self.assertEqual([frame[-2:] for frame in sent[:2]], [["SEGMENT", SEGMENT]] * 2)
        self.assertTrue(all("SEGMENT" not in frame for frame in sent[2:]))


class AsyncSegmentFrameTests(unittest.TestCase):
    def test_the_async_calls_send_it_too(self):
        import asyncio
        from crowkis import AsyncCrowkisClient

        client = AsyncCrowkisClient(tenant="acme")
        sent = []

        async def execute_async(*args):
            sent.append([a.decode() if isinstance(a, bytes) else a for a in args])
            return None

        client.execute_async = execute_async  # type: ignore[assignment]
        asyncio.run(client.cset_async("q", "a", segment=SEGMENT))
        asyncio.run(client.cget_async("q", segment=SEGMENT))
        asyncio.run(client.cget_async("q"))
        self.assertEqual([f[-2:] for f in sent[:2]], [["SEGMENT", SEGMENT]] * 2)
        self.assertNotIn("SEGMENT", sent[2])


if __name__ == "__main__":
    unittest.main()
