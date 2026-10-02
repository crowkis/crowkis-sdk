"""Tests for the Pipecat processors on CallSession. Skipped unless pipecat-ai is installed
(pip install "crowkis[pipecat]"). The decisions themselves are tested framework-free in
test_call_bridge.py; these check that frames are wired to the bridge correctly.
"""

import asyncio
import importlib.util
import unittest

HAVE_PIPECAT = importlib.util.find_spec("pipecat") is not None


@unittest.skipUnless(HAVE_PIPECAT, "pipecat-ai not installed")
class PipecatCallTests(unittest.TestCase):
    def setUp(self):
        from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame  # noqa: F401
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.frame_processor import FrameDirection

        from crowkis.integrations.pipecat_call import call_processors
        from crowkis.session import CallSession
        from crowkis.turn import TurnFrame

        class Client:
            def __init__(self):
                self.tools = {}

            def ctoolget(self, tool, key, tenant=None):
                return self.tools.get((tool, key))

            def ctoolset(self, tool, key, value, ex=None, tenant=None):
                self.tools[(tool, key)] = value

        class Agent:
            tenant = "t"

            def __init__(self):
                self.store, self._client = {}, Client()

            def ask(self, key, **kw):
                if key in self.store:
                    return {"route": "cache", "answer": self.store[key], "confidence": 0.99}
                return {"route": "expensive", "answer": None, "confidence": 0.0}

            def learn(self, key, answer, ttl=None, template=False):
                self.store[key] = answer

        class Scripted:
            def understand(self, turn, state):
                return TurnFrame.from_dict({"kind": "general", "subject": "none", "confidence": 0.9,
                                            "question": turn, "question_type": "policy"})

        self.LLMContext, self.Direction = LLMContext, FrameDirection
        self.agent = Agent()
        self.gate, self.writeback, self.audio = call_processors(
            CallSession(self.agent, Scripted()), voice="priya", sample_rate=24000)

    def _push(self, processor, frame):
        pushed = []

        async def capture(f, direction=None):
            pushed.append(f)

        processor.push_frame = capture
        asyncio.run(processor.process_frame(frame, self.Direction.DOWNSTREAM))
        return pushed

    def test_a_miss_reaches_the_llm_with_only_the_question_and_the_system_prompt(self):
        from pipecat.frames.frames import LLMContextFrame

        ctx = self.LLMContext(messages=[{"role": "system", "content": "Be brief."},
                                        {"role": "user", "content": "My name is Rahul."},
                                        {"role": "user", "content": "Do you price match?"}])
        out = self._push(self.gate, LLMContextFrame(context=ctx))
        sent = out[0].context.messages
        self.assertEqual([m["content"] for m in sent], ["Be brief.", "Do you price match?"])

    def test_full_turn_saves_the_answer_and_its_whole_audio_then_replays_it(self):
        from pipecat.frames.frames import (BotStoppedSpeakingFrame, LLMContextFrame, LLMFullResponseEndFrame,
                                           LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame)

        ctx = lambda: self.LLMContext(messages=[{"role": "user", "content": "Do you price match?"}])  # noqa: E731
        self._push(self.gate, LLMContextFrame(context=ctx()))
        self._push(self.writeback, LLMFullResponseStartFrame())
        self._push(self.writeback, LLMTextFrame("Yes, we match "))
        self._push(self.audio, TTSAudioRawFrame(b"AAAA", 24000, 1))     # TTS starts mid-answer
        self._push(self.writeback, LLMTextFrame("any listed price."))
        self._push(self.writeback, LLMFullResponseEndFrame())
        self._push(self.audio, TTSAudioRawFrame(b"BBBB", 24000, 1))
        self._push(self.audio, BotStoppedSpeakingFrame())
        self.assertEqual(self.agent.store["[kb=1] Do you price match?"], "Yes, we match any listed price.")
        self.assertEqual(len(self.agent._client.tools), 1)

        out = self._push(self.gate, LLMContextFrame(context=ctx()))
        self.assertIsInstance(out[0], TTSAudioRawFrame)
        self.assertEqual(out[0].audio, b"AAAABBBB")

    def test_a_hit_is_spoken_without_the_llm(self):
        from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame

        self.agent.store["[kb=1] Do you price match?"] = "Yes, we match any listed price."
        ctx = self.LLMContext(messages=[{"role": "user", "content": "Do you price match?"}])
        out = self._push(self.gate, LLMContextFrame(context=ctx))
        self.assertIsInstance(out[0], TTSSpeakFrame)
        self.assertEqual(out[0].text, "Yes, we match any listed price.")


if __name__ == "__main__":
    unittest.main()
