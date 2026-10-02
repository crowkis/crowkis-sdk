"""Framework-free tests for CallBridge, the voice-pipeline logic behind the Pipecat processors
(turn understanding v2.2, part 5). Run:  python -m pytest tests/ -q
"""

import base64
import json
import time
import unittest

from crowkis.integrations.call_bridge import TTS_TOOL, CallBridge
from crowkis.session import CallSession
from crowkis.turn import TurnFrame


class FakeClient:
    def __init__(self, slow=0.0, broken=False):
        self.tools, self.slow, self.broken = {}, slow, broken

    def ctoolget(self, tool, key, tenant=None):
        if self.broken:
            raise ConnectionError("down")
        time.sleep(self.slow)
        return self.tools.get((tool, key))

    def ctoolset(self, tool, key, value, ex=None, tenant=None):
        self.tools[(tool, key)] = value


class FakeAgent:
    tenant = "t"

    def __init__(self, client=None):
        self.store, self._client = {}, client or FakeClient()

    def ask(self, key, **kw):
        if key in self.store:
            return {"route": "cache", "answer": self.store[key], "confidence": 0.99}
        return {"route": "expensive", "answer": None, "confidence": 0.0}

    def learn(self, key, answer, ttl=None, template=False):
        self.store[key] = answer


class Scripted:
    def __init__(self, frames):
        self.frames = frames

    def understand(self, turn, state):
        return TurnFrame.from_dict(self.frames.get(turn))


SHIP = "How long does shipping take?"
FRAMES = {
    SHIP: {"kind": "general", "subject": "none", "confidence": 0.9, "question": SHIP, "question_type": "policy"},
    "Where is my order?": {"kind": "personal", "subject": "self", "confidence": 0.9},
}
SYSTEM = {"role": "system", "content": "You are the store's voice assistant."}


def bridge(agent=None, **kw):
    agent = agent or FakeAgent()
    return CallBridge(CallSession(agent, Scripted(FRAMES), **kw), voice="priya", sample_rate=24000), agent


def ctx(*user_turns):
    return [SYSTEM] + [{"role": "user", "content": t} for t in user_turns]


class ContextTests(unittest.TestCase):
    def test_a_miss_keeps_system_prompt_and_tools_but_drops_call_history(self):
        b, _ = bridge()
        d = b.on_context(ctx("My name is Rahul, order 55512.", SHIP), tools=["lookup_order"])
        self.assertEqual(d.action, "model")
        self.assertEqual(d.messages, [SYSTEM, {"role": "user", "content": SHIP}])
        self.assertEqual(d.tools, ["lookup_order"])
        self.assertNotIn("Rahul", json.dumps(d.messages))

    def test_a_personal_turn_gets_the_whole_call(self):
        b, _ = bridge()
        messages = ctx("Hi, I'm Rahul.", "Where is my order?")
        self.assertEqual(b.on_context(messages).messages, messages)

    def test_a_non_user_last_message_goes_to_the_model_unrecorded(self):
        b, _ = bridge()
        d = b.on_context([SYSTEM, {"role": "assistant", "content": "Could you repeat that?"}])
        self.assertEqual(d.action, "model")
        self.assertEqual(b.on_answer("Sure."), "not_recorded")

    def test_list_of_parts_content_is_read(self):
        b, _ = bridge()
        d = b.on_context([SYSTEM, {"role": "user", "content": [{"type": "text", "text": SHIP}]}])
        self.assertEqual(d.messages[-1]["content"], SHIP)

    def test_a_session_error_falls_back_to_the_model_never_silence(self):
        b, _ = bridge()
        b.session.handle = lambda said: (_ for _ in ()).throw(RuntimeError("boom"))
        d = b.on_context(ctx(SHIP))
        self.assertEqual(d.action, "model")
        self.assertEqual(b.counts["errors"], 1)


class AudioTests(unittest.TestCase):
    def test_saved_answer_audio_is_stored_whole_and_replayed_next_time(self):
        agent = FakeAgent()
        b, _ = bridge(agent)
        b.on_context(ctx(SHIP))
        b.on_tts_audio(b"AAAA")            # streaming TTS starts before the answer is complete
        self.assertEqual(b.on_answer("Shipping takes 3 to 5 days."), "saved")
        b.on_tts_audio(b"BBBB")
        self.assertTrue(b.on_bot_stopped())

        b2, _ = bridge(agent)
        d = b2.on_context(ctx(SHIP))
        self.assertEqual((d.action, d.audio), ("play_audio", b"AAAABBBB"))

    def test_personal_answer_audio_is_never_stored(self):
        agent = FakeAgent()
        b, _ = bridge(agent)
        b.on_context(ctx("Where is my order?"))
        b.on_tts_audio(b"PERSONAL")
        b.on_answer("Your order arrives Tuesday.")
        self.assertFalse(b.on_bot_stopped())
        self.assertEqual(agent._client.tools, {})

    def test_replayed_audio_is_not_recorded_into_the_next_clip(self):
        agent = FakeAgent()
        b, _ = bridge(agent)
        b.on_context(ctx(SHIP))
        b.on_answer("Shipping takes 3 to 5 days.")
        b.on_tts_audio(b"CLIP")
        b.on_bot_stopped()
        d = b.on_context(ctx(SHIP))
        self.assertEqual(d.action, "play_audio")
        b.on_tts_audio(d.audio)            # the gate's own playback passes the audio processor
        self.assertFalse(b.on_bot_stopped())

    def test_interruption_discards_the_clip_and_the_save(self):
        agent = FakeAgent()
        b, _ = bridge(agent)
        b.on_context(ctx(SHIP))
        b.on_tts_audio(b"HALF")
        b.on_interruption()
        self.assertEqual(b.on_answer("Shipping takes 3 to 5 days."), "not_recorded")
        self.assertFalse(b.on_bot_stopped())
        self.assertEqual(agent.store, {})

    def test_the_audio_key_carries_voice_rate_and_format(self):
        b, _ = bridge()
        key = json.loads(b._key("hello"))
        self.assertEqual(key, {"voice": "priya", "text": "hello", "sample_rate": 24000, "format": "pcm16"})

    def test_bad_or_slow_audio_cache_means_synthesise(self):
        client = FakeClient()
        b, agent = bridge(FakeAgent(client))
        agent.store["[kb=1] " + SHIP] = "Shipping takes 3 to 5 days."
        client.tools[(TTS_TOOL, b._key("Shipping takes 3 to 5 days."))] = "not base64!!"
        self.assertEqual(b.on_context(ctx(SHIP)).action, "speak_text")
        slow = FakeAgent(FakeClient(slow=0.5))
        slow.store["[kb=1] " + SHIP] = "Shipping takes 3 to 5 days."
        slow._client.tools[(TTS_TOOL, b._key("Shipping takes 3 to 5 days."))] = base64.b64encode(b"X").decode()
        b2, _ = bridge(slow)
        b2.audio_budget_ms = 20
        self.assertEqual(b2.on_context(ctx(SHIP)).action, "speak_text")


if __name__ == "__main__":
    unittest.main()
