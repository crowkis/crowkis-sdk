"""Chat and voice on a real server share nothing private (CROWKIS_CONFORMANCE_SERVER=1).

Each run uses made-up words, so old data on the server and repeated runs never interfere.
One channel saves a general answer and a caller's private details; a fresh session of the
other channel (another call, another agent id) asks. Privacy: nothing the second channel
gets back, no write the SDK sent and no raw lookup holds the details.
Sharing: a general answer stays inside its channel (the segment holds ``channel=``), which
the same-channel controls prove and the cross-channel cases assert (v4 P5 item 5).

    CROWKIS_CONFORMANCE_SERVER=1 CROWKIS_HOST=... CROWKIS_PORT=... CROWKIS_AUTH_TOKEN=... \
        CROWKIS_TENANT=voice python -m pytest tests/test_cross_channel_server.py
"""

import os
import time
import unittest
import uuid

import crowkis
from crowkis.channels.chat import Chat
from crowkis.understanding.model.frame import TurnFrame

REAL = os.environ.get("CROWKIS_CONFORMANCE_SERVER") == "1"
# Read once, at import: conftest.py clears the CROWKIS_* variables for each test.
_SERVER = {name: os.environ.get("CROWKIS_" + name.upper()) for name in ("host", "port", "auth_token", "tenant")}
FINDABLE_S = 10.0  # a new answer is findable on a real server within about a second
SEPARATE_S = 3.0  # waiting for something that must not happen: shorter
# What the two channels build their cache segments from (kb version, language, channel).
SEGMENTS = (None, "kb=1;channel=voice", "kb=1;lang=und;channel=chat")


class Scripted:
    def __init__(self, frames):
        self.frames = frames

    def understand(self, turn, state):
        return TurnFrame.from_dict(self.frames[turn])


class Words:
    """One run's made-up words: nothing already on the server can match them."""

    def __init__(self):
        h = uuid.uuid4().hex[:8]
        # Letters only: a word with digits reads as an identifier and makes a question private.
        u = "".join(chr(97 + int(c, 16)) for c in h)
        self.u = u
        self.general_q = f"What are the opening hours of the zorblax{u} store?"
        self.general_a = f"The zorblax{u} store opens at 9 am."
        self.name = f"Quillon Vrexbane{u}"
        self.phone = "98" + str(int(h, 16))[:7].ljust(7, "3")
        self.order = f"ZB{h.upper()}"
        self.fact = f"my cat Mipsy{u} is allergic to fish"
        self.intro = f"My name is {self.name}, my phone is {self.phone}, my order {self.order} is late and {self.fact}."
        self.private_q = f"Where is my order {self.order}, do you have my phone {self.phone} for {self.name}?"
        self.private_a = (f"Hello {self.name}, order {self.order} ships soon; we will call {self.phone}. "
                          f"Noted that {self.fact}.")
        self.stated = f"This is {self.name} calling, my phone is {self.phone} and my order is {self.order}."
        self.leaky_a = f"Sure {self.name}, the zorblax{u} store opens at 9 am."
        self.secrets = [self.name, self.phone, self.order, f"Mipsy{u}"]
        self.frames = {
            self.general_q: {"kind": "general", "subject": "none", "confidence": 0.9, "question": self.general_q,
                             "entities": [{"text": f"zorblax{u} store", "type": "product"}]},
            self.intro: {"kind": "personal", "subject": "self", "confidence": 0.9,
                         "entities": [{"text": self.name, "type": "person"}, {"text": self.phone, "type": "phone"},
                                      {"text": self.order, "type": "order_id"}]},
            self.stated: {"kind": "personal", "subject": "self", "confidence": 0.9,
                          "entities": [{"text": self.name, "type": "person"}, {"text": self.phone, "type": "phone"},
                                       {"text": self.order, "type": "order_id"}]},
            self.private_q: {"kind": "personal", "subject": "self", "confidence": 0.9,
                             "entities": [{"text": self.order, "type": "order_id"}]},
        }

    def agent(self, channel):
        return f"xchan-{channel}-{self.u}"

    def leaks(self, obj):
        text = repr(obj).lower()
        return [s for s in self.secrets if s.lower() in text]


def served_text(result, model_reply):
    """What the caller got if it came from the cache, None if the model had to answer."""
    return None if result.text == model_reply else result.text


@unittest.skipUnless(REAL, "needs a real server: CROWKIS_CONFORMANCE_SERVER=1")
class CrossChannelServerTests(unittest.TestCase):
    def setUp(self):
        settings = {k: (int(v) if k == "port" else v) for k, v in _SERVER.items() if v}
        self.client = crowkis.CrowkisClient(**settings)
        self.addCleanup(self.client.close)
        self.writes = []
        cset = self.client.cset

        def spy(*args, **kwargs):
            self.writes.append((args, kwargs))
            return cset(*args, **kwargs)

        self.client.cset = spy
        self.w = Words()

    # -- the two channels ---------------------------------------------------------
    def chat_ask(self, thread, texts, reply):
        agent = crowkis.Agent(client=self.client, agent_id=self.w.agent("chat"))
        chat = Chat(agent, Scripted(self.w.frames), system="You are the store's assistant.")
        history, out = [], []
        for text in texts:
            history.append({"role": "user", "content": text})
            out.append(chat.turn(thread, history, answer=lambda m: reply))
            history.append({"role": "assistant", "content": out[-1].text})
        return out

    def voice(self, understood=True):
        extra = {}
        if understood:
            understander = Scripted(self.w.frames)
            extra = {"classifier": crowkis.LLMClassifier(understander), "rewriter": crowkis.LLMRewriter(understander)}
        session = crowkis.voice_session(client=self.client, agent_id=self.w.agent("voice"), **extra)
        self.addCleanup(session.agent.close)
        return session

    def voice_ask(self, texts, reply, understood=True):
        session = self.voice(understood)
        return [session.answer(text, lambda m: reply) for text in texts]

    def until_served(self, ask, wait=FINDABLE_S):
        """The cached text once the answer is findable, or None at the deadline."""
        deadline = time.monotonic() + wait
        while True:
            served = ask()
            if served is not None or time.monotonic() > deadline:
                return served
            time.sleep(0.5)

    def assert_private_stayed_private(self, got):
        self.assertEqual(self.w.leaks(got), [], "a private detail came back through the other channel")
        self.assertEqual(self.w.leaks(self.writes), [], "a private detail was written to the shared cache")
        self.assertTrue(self.writes, "the first channel saved nothing: this proves nothing")
        for question in (self.w.private_q, self.w.intro, *self.w.secrets):
            for segment in SEGMENTS:
                hit = self.client.cget_hit(question, **({"segment": segment} if segment else {}))
                self.assertEqual(self.w.leaks(hit), [], f"raw lookup of {question!r} in {segment} found a detail")

    # -- direction 1: chat saves, voice asks --------------------------------------
    def chat_saves(self):
        general = self.chat_ask("t-general", [self.w.general_q], self.w.general_a)[0]
        self.assertEqual(general.outcome, "saved", general)
        private = self.chat_ask("t-private", [self.w.intro, self.w.private_q], self.w.private_a)
        self.assertTrue(all(r.outcome != "saved" for r in private), private)  # never shared
        time.sleep(1.5)

    def test_chat_to_voice_keeps_private_details_private(self):
        self.chat_saves()
        for understood in (True, False):
            got = self.voice_ask([self.w.general_q, self.w.intro, self.w.private_q], "Sorry, one moment.", understood)
            self.assert_private_stayed_private(got)

    def test_chat_to_voice_does_not_serve_the_general_answer(self):
        # By design (v4 P5 item 5): every segment holds channel=<name>, so channels never serve each other's answers.
        self.chat_saves()
        got = self.until_served(lambda: served_text(self.voice_ask([self.w.general_q], "LLM-VOICE")[0], "LLM-VOICE"), SEPARATE_S)
        self.assertIsNone(got)

    # -- direction 2: voice saves, chat asks --------------------------------------
    def voice_saves(self):
        session = self.voice()
        general = session.answer(self.w.general_q, lambda m: self.w.general_a)
        self.assertTrue(general.stored, general)
        for text in (self.w.intro, self.w.private_q):
            decision = session.answer(text, lambda m: self.w.private_a)
            self.assertFalse(decision.stored, decision)  # never shared
        time.sleep(1.5)

    def test_voice_to_chat_keeps_private_details_private(self):
        self.voice_saves()
        got = self.chat_ask("t-other", [self.w.general_q, self.w.intro, self.w.private_q], "Sorry, one moment.")
        self.assert_private_stayed_private(got)

    def test_voice_to_chat_does_not_serve_the_general_answer(self):
        # By design (v4 P5 item 5), as above.
        self.voice_saves()
        got = self.until_served(lambda: served_text(self.chat_ask("t-g2", [self.w.general_q], "LLM-CHAT")[0], "LLM-CHAT"), SEPARATE_S)
        self.assertIsNone(got)

    # -- details stated early, repeated by the model in a general answer ---------------
    def assert_stated_details_not_shared(self, first_reply, second_caller):
        self.assertNotEqual(first_reply.stored, True, "an answer repeating the caller's details was saved shared")
        self.assertEqual(self.w.leaks(self.writes), [], "a stated detail was written to the shared cache")
        time.sleep(1.5)
        self.assertEqual(self.w.leaks(second_caller()), [], "a second caller got the first caller's details")

    def test_voice_answer_repeating_stated_details_is_not_shared(self):
        session = self.voice()
        session.answer(self.w.stated, lambda m: "Thank you, noted.")
        first = session.answer(self.w.general_q, lambda m: self.w.leaky_a)
        self.assert_stated_details_not_shared(first, lambda: self.voice_ask([self.w.general_q], "LLM-VOICE"))

    def test_chat_answer_repeating_stated_details_is_not_shared(self):
        first = self.chat_ask("t-stated", [self.w.stated, self.w.general_q], self.w.leaky_a)[1]
        self.assertNotEqual(first.outcome, "saved", first)
        self.assert_stated_details_not_shared(
            type("R", (), {"stored": False}), lambda: self.chat_ask("t-second", [self.w.general_q], "LLM-CHAT"))

    # -- controls: the lookup, the wait and the checks do work within a channel ----
    def test_control_chat_to_chat_shares_the_general_answer(self):
        self.chat_saves()
        got = self.until_served(lambda: served_text(
            self.chat_ask(f"t-{uuid.uuid4().hex[:6]}", [self.w.general_q], "LLM-CHAT")[0], "LLM-CHAT"))
        self.assertEqual(got, self.w.general_a)

    def test_control_voice_to_voice_shares_the_general_answer(self):
        self.voice_saves()
        got = self.until_served(lambda: served_text(self.voice_ask([self.w.general_q], "LLM-VOICE")[0], "LLM-VOICE"))
        self.assertEqual(got, self.w.general_a)


if __name__ == "__main__":
    unittest.main()
