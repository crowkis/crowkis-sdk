"""A name the caller stated earlier in the call is never saved into a shared answer that repeats it
(voice and Chat). Controls: a general answer is still saved; a name the caller did NOT state is
unaffected; "I'm looking for ..." does not register a name."""
import time
import unittest

import crowkis
from crowkis.channels.chat import Chat
from crowkis.understanding.word_rules.personal import _stated_names

from conformance import ConformanceStore
from test_chat import GENERAL, Model, Scripted, SegmentedAgent

INTRO_ANSWER = "Hi"


def _voice(turns):
    store = ConformanceStore()
    s = crowkis.voice_session(client=store, agent_id="a", voice=None)
    for said, answer in turns:
        d = s.decide(said)
        if d.needs_model:
            s.record(d, answer)
    time.sleep(0.5)
    return [w[0] for w in store.writes if w[2] is False]  # shared answers saved


def _chat(intro, question, answer, general_intro=False):
    first = dict(GENERAL, question=intro) if general_intro else {"kind": "personal", "subject": "self", "confidence": 0.9}
    frames = {intro: first,
              question: dict(GENERAL, question=question)}
    agent = SegmentedAgent()
    chat = Chat(agent, Scripted(frames), system="You are Acme's assistant.")
    history = []
    for turn, reply in ((intro, INTRO_ANSWER), (question, answer)):
        history.append({"role": "user", "content": turn})
        out = chat.turn("t", history, answer=Model(reply))
        history.append({"role": "assistant", "content": out.text})
    return [s[2] for s in agent.saved if s[2] != INTRO_ANSWER]  # a general intro is itself saved


INTROS = ["my name is Rahul Verma", "I'm Rahul Verma", "I am Rahul", "this is Rahul", "call me Rahul",
          "name's Rahul", "mera naam Rahul hai", "mera naam rahul verma hai"]
LEAKS = ["Refunds in 7 days, Rahul.", "Sure Rahul, refunds take 7 days.", "Refunds in 7 days, rahul verma.",
         "Dear Mr Verma, refunds take 7 days."]


def _pairs():
    """(intro, leaking answer): the answer says a word of the name the intro gave."""
    return [(i, l) for i in INTROS for l in LEAKS if any(w in i.lower() for w in _name_in(l))]


def _name_in(answer):
    return [w for w in ("rahul", "verma") if w in answer.lower()]


class StatedNameTests(unittest.TestCase):
    def test_voice_answer_repeating_a_stated_name_is_not_shared(self):
        for intro, leak in _pairs():
            with self.subTest(intro=intro, leak=leak):
                self.assertEqual(_voice([(intro, INTRO_ANSWER), ("what is the refund policy", leak)]), [])

    def test_chat_answer_repeating_a_stated_name_is_not_shared(self):
        for intro, leak in _pairs():
            with self.subTest(intro=intro, leak=leak):
                self.assertEqual(_chat(intro, "what is the refund policy", leak), [])

    def test_controls_general_answer_is_still_saved(self):
        answer = "Refunds take 7 days."
        self.assertEqual(_voice([("my name is Rahul Verma", INTRO_ANSWER), ("what is the refund policy", answer)]),
                         ["what is the refund policy"])
        self.assertEqual(_chat("my name is Rahul Verma", "what is the refund policy", answer), [answer])

    def test_controls_an_unstated_name_is_unaffected(self):
        answer = "Dr Meera is available Monday."
        self.assertEqual(_voice([("my name is Rahul Verma", INTRO_ANSWER), ("who is available on monday", answer)]),
                         ["who is available on monday"])
        self.assertEqual(_chat("my name is Rahul Verma", "who is available on monday", answer), [answer])

    def test_controls_not_a_name(self):
        for intro in ("I'm looking for the refund policy", "I am calling about refunds", "this is urgent",
                      "I'm not sure", "this is the refund question"):
            with self.subTest(intro=intro):
                self.assertEqual(_stated_names([intro]), set())
        self.assertEqual(_stated_names(["I'm looking for the refund policy"]), set())
        saved = _voice([("I'm looking for the refund policy", INTRO_ANSWER), ("what is the refund policy", "Refunds take 7 days.")])
        self.assertEqual(saved, ["what is the refund policy"])

    def test_names_are_read_from_the_original_case(self):
        self.assertEqual(_stated_names(["my name is Rahul Verma"]), {"rahul", "verma"})
        self.assertEqual(_stated_names(["I'm Priya, and I want a refund"]), {"priya"})
        self.assertEqual(_stated_names(["mera naam Rahul hai"]), {"rahul"})


MORE_INTROS = ["Rahul here", "rahul here", "hello, Rahul this side", "Rahul speaking", "myself Rahul", "myself rahul verma",
               "it's Rahul", "its rahul", "it is Rahul", "you're speaking with Rahul", "mera naam hai Rahul",
               "my good name is Rahul", "the name is Rahul", "my first name is Rahul"]
CHAT_INTROS = [i for i in MORE_INTROS if i != "myself rahul verma"]  # lower-case "myself X" is a weak lead in Chat


class MoreNamePhrasingTests(unittest.TestCase):
    def test_voice_every_phrasing_keeps_the_name_out_of_shared_answers(self):
        for intro in MORE_INTROS:
            with self.subTest(intro=intro):
                self.assertEqual(_voice([(intro, INTRO_ANSWER), ("what is the refund policy", "Refunds in 7 days, Rahul.")]), [])

    def test_chat_every_phrasing_keeps_the_name_out_of_shared_answers(self):
        for intro in CHAT_INTROS:
            with self.subTest(intro=intro):
                self.assertEqual(_chat(intro, "what is the refund policy", "Refunds in 7 days, Rahul."), [])

    def test_three_name_words_and_glued_honorific(self):
        self.assertEqual(_stated_names(["my name is Priya Iyer Sharma"]), {"priya", "iyer", "sharma"})
        self.assertEqual(_voice([("my name is Priya Iyer Sharma", INTRO_ANSWER), ("what is the refund policy", "Refunds in 7 days, Ms Sharma.")]), [])
        for leak in ("Refunds in 7 days, Rahulji.", "Refunds in 7 days, Rahul-ji.", "Refunds in 7 days, Rahul jee."):
            with self.subTest(leak=leak):
                self.assertEqual(_voice([("my name is Rahul Verma", INTRO_ANSWER), ("what is the refund policy", leak)]), [])
                self.assertEqual(_chat("my name is Rahul Verma", "what is the refund policy", leak), [])

    def test_controls_not_names(self):
        for text in ("the menu here", "who is speaking", "what is the menu here", "call me tomorrow", "call me back",
                     "it is open on sundays", "it's free", "speaking of refunds"):
            with self.subTest(text=text):
                self.assertEqual(_stated_names([text]), set())
        self.assertEqual(_voice([("what is the menu here", "Hi"), ("what is the refund policy", "Refunds take 7 days.")]),
                         ["what is the refund policy"])  # "here" makes the first a private question: nothing was taken as a name


class SpokenAndLowercaseTests(unittest.TestCase):
    def test_lowercase_and_trailing_words(self):
        for intro in ("this is harpreet iyer calling", "I am harpreet iyer", "this is Harpreet Iyer calling"):
            with self.subTest(intro=intro):
                saved = _voice([(intro, "Noted."), ("how can I track a parcel", "Tracking links are sent when a parcel ships, harpreet iyer.")])
                self.assertEqual(saved, [])
                self.assertEqual(_stated_names([intro]), {"harpreet", "iyer"})

    def test_chat_lowercase_name_is_kept_out_of_shared_answers(self):
        leak = "Tracking links are sent when a parcel ships, harpreet iyer."
        for general_intro in (True, False):
            with self.subTest(general_intro=general_intro):
                self.assertEqual(_chat("i am harpreet iyer", "how can I track a parcel", leak, general_intro), [])

    def test_chat_question_rules_still_read_only_capitalised_names(self):
        # test_chat's "I'm diabetic" cases cover the behaviour; this is the reason they stay as before.
        self.assertEqual(_stated_names(["I'm diabetic"], lowercase=False), set())
        self.assertEqual(_stated_names(["I'm Priya"], lowercase=False), {"priya"})

    def test_a_phone_said_in_words_is_not_shared(self):
        phone = "six seven zero eight six six eight one zero two"
        saved = _voice([("my phone number is " + phone, "Noted."), ("how do I contact support", f"Use the help centre or the support line, {phone}.")])
        self.assertEqual(saved, [])
        saved = _voice([("my phone number is 6708668102", "Noted."), ("how do I contact support", f"Call {phone}.")])
        self.assertEqual(saved, [])

    def test_control_ordinary_number_words_are_saved(self):
        saved = _voice([("my phone number is six seven zero eight six six eight one zero two", "Noted."),
                        ("what are your hours", "We are open from nine to six, Monday to Saturday.")])
        self.assertEqual(saved, ["what are your hours"])


if __name__ == "__main__":
    unittest.main()
