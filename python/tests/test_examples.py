"""The custom voice loop examples run, and do what they say: a miss streams the LLM into
the TTS and is saved; the same question again is answered from the cache; a barge-in
stops the stream and saves nothing."""

import asyncio
import importlib.util
import unittest
from pathlib import Path

from crowkis import Agent, AsyncVoiceSession, VoiceSession

from voice_turns_scenarios import SceneStore

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "python_custom_voice_loop.py"


def _load():
    spec = importlib.util.spec_from_file_location("custom_voice_loop", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CustomLoopTests(unittest.TestCase):
    def test_a_miss_then_a_hit(self):
        loop = _load()
        store = SceneStore()
        session = AsyncVoiceSession.wrap(VoiceSession(Agent("caller", client=store), voice="v"))
        said = asyncio.run(loop.main(session))
        self.assertEqual([s.strip() for s in said], ["Refunds take five business days to reach your card."] * 2)
        self.assertEqual(len(store.writes), 1)  # saved once; the second time from the cache

    def test_a_barge_in_saves_nothing(self):
        loop = _load()
        store = SceneStore()
        session = AsyncVoiceSession.wrap(VoiceSession(Agent("caller", client=store), voice="v"))
        sent = []

        async def tts(text):
            sent.append(text)

        async def play(audio):
            pass

        said = asyncio.run(loop.run_call(session, loop.caller(["what is your refund policy"]), loop.openai_llm,
                                         tts, play, barged_in=lambda: len(sent) >= 2))
        self.assertEqual(len(sent), 2)
        self.assertEqual(store.writes, [])
        self.assertEqual(len(said), 1)


if __name__ == "__main__":
    unittest.main()
