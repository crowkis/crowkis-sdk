"""Chat's ``system`` can carry one user's details ("The user is Asha Rao"). A shared answer
that repeats them was shaped by that user and is never saved for everyone, as in voice
(test_voice_prompt_guard.py)."""
import unittest

from crowkis.chat import Chat
from crowkis.session import CallSession

from test_chat import GENERAL, Model, Scripted, SegmentedAgent

QUESTION = "What time do you open?"
FRAMES = {QUESTION: dict(GENERAL, question=QUESTION)}
PERSONAL = "You are Acme's assistant. The user is Asha Rao, a Gold member since March."
PLAIN = "You are Acme's assistant. Be brief and friendly."


def _turn(system, reply, agent=None):
    agent = agent or SegmentedAgent()
    model = Model(reply)
    chat = Chat(agent, Scripted(FRAMES), system=system)
    return agent, model, chat.turn("thread-1", [{"role": "user", "content": QUESTION}], answer=model)


class ChatPromptGuardTests(unittest.TestCase):
    def test_an_answer_repeating_a_detail_from_the_system_prompt_is_never_saved(self):
        for reply in ("Hi Asha! We open at nine.", "As a Gold member, you can come in from eight.",
                      "Asha, we open at nine."):
            with self.subTest(reply=reply):
                agent, model, result = _turn(PERSONAL, reply)
                self.assertEqual(result.text, reply, "the user still gets the answer")
                self.assertEqual(result.outcome, "refused:prompt_detail")
                self.assertEqual(agent.saved, [])
                self.assertEqual(model.read[0][0], {"role": "system", "content": PERSONAL})

    def test_must_still_work_an_answer_without_them_is_saved(self):
        agent, _, result = _turn(PERSONAL, "We open at nine.")
        self.assertEqual(result.outcome, "saved")
        self.assertEqual(len(agent.saved), 1)

    def test_must_still_work_a_prompt_with_no_user_details_never_blocks(self):
        for reply in ("Hi! We open at nine.", "Acme opens at nine."):
            with self.subTest(reply=reply):
                agent, _, result = _turn(PLAIN, reply)
                self.assertEqual(result.outcome, "saved")
                self.assertEqual(len(agent.saved), 1)

    def test_a_call_session_without_instructions_is_unchanged(self):
        session = CallSession(SegmentedAgent(), Scripted(FRAMES))
        self.assertEqual(session.instructions, "")


if __name__ == "__main__":
    unittest.main()
