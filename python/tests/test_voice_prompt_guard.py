"""The system prompt goes to the model, and an answer that repeats a caller's detail from
it is never shared.

The Pipecat processors used to send the model only the caller's question on a model
turn, dropping the app's system prompt and its tools. Now the model reads the system
messages before the conversation and keeps the tools. Some apps put one caller's details
in the system prompt ("The caller is Asha Rao, account 99812"), so before an answer is
shared it is checked: one that repeats such a detail ("Hi Asha! We open at nine.") stays
in that call. The same check covers answer(system=), record(system=) and respond(system=).
fixtures/prompt-guard-cases.json is checked by the Node tests too."""

import asyncio
import json
import unittest
from pathlib import Path

from crowkis.voice import _prompt_details, _repeats_prompt_details, _reset_prompt_baselines

from test_voice_stress_bugs import ANSWER, Store, _pipecat, session_on

CASES = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "prompt-guard-cases.json").read_text("utf-8"))
PROMPT = CASES["prompt"]


class DetectorTests(unittest.TestCase):
    def test_the_details_of_a_prompt(self):
        words, numbers = _prompt_details(PROMPT)
        self.assertEqual((sorted(words), sorted(numbers)),
                         (CASES["details"]["words"], CASES["details"]["numbers"]))
        for prompt, want_words, want_numbers in CASES["prompts"]:
            with self.subTest(prompt=prompt):
                words, numbers = _prompt_details(prompt)
                self.assertEqual((sorted(words), sorted(numbers)), (want_words, want_numbers))

    def test_which_answers_repeat_a_detail(self):
        for answer, repeats in CASES["answers"]:
            with self.subTest(answer=answer):
                self.assertEqual(_repeats_prompt_details(answer, CASES["question"], PROMPT), repeats)

    def test_numbers_with_commas_or_a_country_code(self):
        for prompt, answers in CASES["numbers"]:
            for answer, repeats in answers:
                with self.subTest(answer=answer):
                    self.assertEqual(_repeats_prompt_details(answer, "q", prompt), repeats)

    def test_across_calls_whatever_differs_between_callers_is_a_detail(self):
        # Lower-case names, record values, any script: once the agent's prompt has been
        # seen to change, what is not common to every call is this caller's.
        _reset_prompt_baselines()
        question = CASES["across_calls"]["question"]
        for prompt, answer, repeats in CASES["across_calls"]["calls"]:
            with self.subTest(answer=answer):
                self.assertEqual(_repeats_prompt_details(answer, question, prompt, ("t", "voice")), repeats)

    def test_a_business_prompt_never_blocks_sharing_once_it_has_varied(self):
        _reset_prompt_baselines()
        key = ("t", "voice")
        base = "Always greet the customer warmly. You are Acme's assistant for customers of Acme Bank. Caller: {}"
        _repeats_prompt_details("x", "q", base.format("Asha"), key)
        self.assertFalse(_repeats_prompt_details("Always happy to help at Acme Bank.", "q", base.format("Ravi"), key))
        self.assertTrue(_repeats_prompt_details("Ravi, Acme Bank opens at nine.", "q", base.format("Ravi"), key))

    def test_non_latin_names_are_caught_across_calls(self):
        _reset_prompt_baselines()
        key = ("t", "voice")
        base = "Acme assistant. कॉलर: {}"
        _repeats_prompt_details("x", "q", base.format("आशा"), key)
        self.assertTrue(_repeats_prompt_details("रवि, we open at nine.", "q", base.format("रवि"), key))

    def test_a_detail_the_caller_said_themself_is_not_counted_twice(self):
        self.assertFalse(_repeats_prompt_details("Hi Asha!", "hello this is Asha", PROMPT))


class SessionTests(unittest.TestCase):
    def test_answer_with_a_system_prompt(self):
        store = Store()
        session = session_on(store)
        private = session.answer("what are your opening hours", lambda m: "Hi Asha! We open at nine.", system=PROMPT)
        self.assertFalse(private.stored)
        self.assertIn("system prompt", private.not_stored)
        shared = session.answer("how do I reset my password", lambda m: "Open settings, then security.", system=PROMPT)
        self.assertTrue(shared.stored)
        self.assertEqual(store.writes, [("how do I reset my password", "Open settings, then security.", False)])

    def test_a_plain_system_prompt_changes_nothing(self):
        store = Store()
        decision = session_on(store).answer("what are your opening hours", lambda m: "Hi! We open at nine.",
                                            system="You are Acme's assistant. Be brief.")
        self.assertTrue(decision.stored)

    def test_record_and_respond_with_a_system_prompt(self):
        store = Store()
        session = session_on(store)
        decision = session.decide("what are your opening hours")
        session.record(decision, "Hi Asha! We open at nine.", system=PROMPT)
        self.assertFalse(decision.stored)
        stream = session.respond("how do I reset my password", lambda m: iter(["Asha, open ", "settings."]), system=PROMPT)
        list(stream)
        self.assertFalse(stream.decision.stored)
        self.assertEqual(store.writes, [])

    def test_the_async_session_passes_the_system_prompt_on(self):
        from crowkis import AsyncVoiceSession

        store = Store()
        session = AsyncVoiceSession.wrap(session_on(store))

        async def model(messages):
            return "Hi Asha! We open at nine."

        decision = asyncio.run(session.answer("what are your opening hours", model, system=PROMPT))
        self.assertFalse(decision.stored)
        self.assertEqual(store.writes, [])


class PipecatTests(unittest.TestCase):
    def run_gate(self, pc, F, LLMContext, context):
        session = session_on(Store())
        gate, writeback, audio = pc.crowkis_processors(session, sample_rate=16000)
        pushed = []

        async def push(frame, direction=None):
            pushed.append(frame)

        gate.push_frame = push
        asyncio.run(gate.process_frame(F.LLMContextFrame(context=context), "down"))
        return pushed[-1].context, gate

    def test_the_model_reads_the_system_prompt_before_the_question(self):
        pc, F, LLMContext = _pipecat()
        context, gate = self.run_gate(pc, F, LLMContext, LLMContext(messages=[
            {"role": "system", "content": "You are Acme's assistant."},
            {"role": "user", "content": "I am Priya, account 4471."},
            {"role": "assistant", "content": "Hello Priya."},
            {"role": "user", "content": "what is your refund policy"},
        ]))
        self.assertEqual(context.messages, [
            {"role": "system", "content": "You are Acme's assistant."},
            {"role": "user", "content": "what is your refund policy"},
        ])  # the instructions, then only the question: nothing else from the call

    def test_the_answer_is_checked_against_the_system_prompt_it_was_written_with(self):
        pc, F, LLMContext = _pipecat()
        store = Store()
        session = session_on(store)
        gate, writeback, audio = pc.crowkis_processors(session, sample_rate=16000)
        frames = []

        async def run():
            async def to_writeback(frame, direction=None):
                frames.append(frame)
            gate.push_frame = to_writeback
            writeback.push_frame = to_writeback
            for question, answer in (("what are your opening hours", "Hi Asha! We open at nine."),
                                     ("how do I reset my password", "Open settings, then security.")):
                ctx = LLMContext(messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": question}])
                await gate.process_frame(F.LLMContextFrame(context=ctx), "down")
                for frame in (F.LLMFullResponseStartFrame(), F.LLMTextFrame(answer), F.LLMFullResponseEndFrame()):
                    await writeback.process_frame(frame, "down")

        asyncio.run(run())
        self.assertEqual(store.writes, [("how do I reset my password", "Open settings, then security.", False)])


try:
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.frames.frames import LLMContextFrame as RealContextFrame
    from pipecat.processors.aggregators.llm_context import LLMContext as RealContext
except ImportError:  # pragma: no cover - pipecat-ai not installed
    RealContext = None


@unittest.skipIf(RealContext is None, "pipecat-ai not installed")
class RealPipecatTests(unittest.TestCase):
    def test_the_model_keeps_the_system_prompt_and_the_tools(self):
        import crowkis.integrations.pipecat as pc

        session = session_on(Store())
        gate, _, _ = pc.crowkis_processors(session, sample_rate=16000)
        pushed = []

        async def push(frame, direction=None):
            pushed.append(frame)

        gate.push_frame = push
        tools = ToolsSchema(standard_tools=[FunctionSchema(name="get_weather", description="weather",
                                                           properties={}, required=[])])
        context = RealContext(messages=[{"role": "system", "content": "You are Acme's phone agent."},
                                        {"role": "user", "content": "what is your refund policy"}],
                              tools=tools, tool_choice="auto")
        asyncio.run(gate.process_frame(RealContextFrame(context=context), "down"))
        sent = pushed[-1].context
        self.assertEqual(sent.get_messages(), [{"role": "system", "content": "You are Acme's phone agent."},
                                               {"role": "user", "content": "what is your refund policy"}])
        self.assertEqual([t.name for t in sent.tools.standard_tools], ["get_weather"])
        self.assertEqual(sent.tool_choice, "auto")


if __name__ == "__main__":
    unittest.main()
