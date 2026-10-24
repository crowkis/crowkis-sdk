"""One test per finding of the second independent review of the voice fixes (14 Oct 2026).

The re-reviewer's own turns, through the path a user takes (VoiceSession.answer, or the
Pipecat processors), next to "must still work" controls. Same cases as
node/test-voice-rereview-fixes.js (the Pipecat ones are Python only).
"""

import asyncio
import base64
import logging
import threading
import time
import unittest

from crowkis.agent import Agent, _wait_for_audio_stores
from crowkis.voice import VoiceSession, _is_personal

from test_voice_stress_bugs import ANSWER, Store, _pipecat, call, session_on, user

Q1 = "Where is my order right now?"
Q2 = "What are your opening hours on weekends?"
Q3 = "Do you deliver to Pune on Sundays?"
PRIVATE = "Your order 55123 for Priya ships Friday to 42 Park Lane."


class PipecatTurnBindingTests(unittest.TestCase):
    """Each response is matched to the context it was generated from; a tool's answer is
    never stored as shared nor paired with a caller turn, whatever order frames arrive in."""

    def setUp(self):
        self.pc, self.f, self.Context = _pipecat()
        self.store = Store()
        self.session = session_on(self.store)
        self.answers = []

        async def on_answer(info):
            self.answers.append(info)

        self.gate, self.writeback, _ = self.pc.crowkis_processors(
            self.session, sample_rate=16000, on_answer=on_answer
        )

    async def ask(self, *said):
        await self.gate.process_frame(self.f.LLMContextFrame(self.Context([user(s) for s in said])), "down")

    async def respond(self, text=None, tool=False, end=True):
        f, wb = self.f, self.writeback
        await wb.process_frame(f.LLMFullResponseStartFrame(), "down")
        if text:
            await wb.process_frame(f.LLMTextFrame(text), "down")
        if tool:
            await wb.process_frame(f.FunctionCallInProgressFrame(), "down")
        if end:
            await wb.process_frame(f.LLMFullResponseEndFrame(), "down")

    async def interrupt(self):
        frame = self.f.InterruptionFrame()
        await self.gate.process_frame(frame, "down")
        await self.writeback.process_frame(frame, "down")

    def tool_context(self, *said):
        return self.Context([user(s) for s in said] + [
            {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "order_status"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "55123 ships Friday"},
        ])

    async def tool_result_sent_back(self, *said):
        """Pipecat's assistant aggregator sends the context with the tool's result back up."""
        await self.writeback.process_frame(self.f.LLMContextFrame(self.tool_context(*said)), "up")

    def pairs(self):
        return [(a["question"], a["answer"], a["stored"]) for a in self.answers]

    def assertToolAnswerNeverShared(self):
        self.assertNotIn(PRIVATE, str(self.store.writes))
        self.assertFalse([a for a in self.answers if a["answer"] == PRIVATE and a["stored"]])
        # Reported, if at all, unpaired ("") or with the turn that called the tool.
        self.assertFalse([a for a in self.answers if a["answer"] == PRIVATE and a["question"] not in ("", Q1, Q2)])

    def run_order(self, steps):
        async def run():
            for step in steps:
                await step()
        self.setUp()
        asyncio.run(run())

    def test_s10_a_tool_then_a_new_question_without_a_barge_in(self):
        # Q2 calls a tool, the caller asks Q3, the tool's answer arrives (no context seen).
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.ask(Q2, Q3),
                        lambda: self.respond(PRIVATE)])
        self.assertToolAnswerNeverShared()
        self.assertEqual(self.store.writes, [])
        # ... then the real answer to Q3: neither can be told apart, so neither is stored.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.ask(Q2, Q3),
                        lambda: self.respond(PRIVATE), lambda: self.respond("Yes, we deliver to Pune on Sundays.")])
        self.assertToolAnswerNeverShared()
        # With the tool's context seen after Q3's, either response may be the tool's: frame
        # order is not trusted, so neither is stored (a lost saving, never a leak).
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.ask(Q2, Q3),
                        lambda: self.tool_result_sent_back(Q2),
                        lambda: self.respond("Yes, we deliver to Pune on Sundays."), lambda: self.respond(PRIVATE)])
        self.assertToolAnswerNeverShared()
        self.assertEqual(self.store.writes, [])
        # The tool's context seen before Q3 is asked: its answer, then Q3's, each in place.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.tool_result_sent_back(Q2),
                        lambda: self.ask(Q2, Q3), lambda: self.respond(PRIVATE),
                        lambda: self.respond("Yes, we deliver to Pune on Sundays.")])
        self.assertToolAnswerNeverShared()
        self.assertEqual(self.store.writes, [(Q3, "Yes, we deliver to Pune on Sundays.", False)])
        # ... and out of that order: the tool's answer first. Still never shared.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.ask(Q2, Q3),
                        lambda: self.tool_result_sent_back(Q2),
                        lambda: self.respond(PRIVATE), lambda: self.respond("Yes, we deliver to Pune on Sundays.")])
        self.assertToolAnswerNeverShared()

    def test_s13_a_barge_in_then_a_late_tool_answer(self):
        # The tool's context is seen: the answer before it was Q2's own, and is stored.
        self.run_order([lambda: self.ask(Q1), lambda: self.respond(tool=True), self.interrupt,
                        lambda: self.ask(Q1, Q2), lambda: self.respond("We open 9 to 5."),
                        lambda: self.tool_result_sent_back(Q1), lambda: self.respond(PRIVATE)])
        self.assertEqual(self.store.writes, [(Q2, "We open 9 to 5.", False)])
        self.assertIn((Q2, "We open 9 to 5.", True), self.pairs())
        self.assertToolAnswerNeverShared()
        # A cancelled tool: nothing is in flight, the next answer is Q2's.
        self.run_order([lambda: self.ask(Q1), lambda: self.respond(tool=True), self.interrupt,
                        lambda: self.writeback.process_frame(self.f.FunctionCallCancelFrame(), "down"),
                        lambda: self.ask(Q1, Q2), lambda: self.respond("We open 9 to 5.")])
        self.assertEqual(self.store.writes, [(Q2, "We open 9 to 5.", False)])
        # No context seen, either order: nothing shared, and nothing paired with Q1.
        for first, second in ((PRIVATE, "We open 9 to 5."), ("We open 9 to 5.", PRIVATE)):
            self.run_order([lambda: self.ask(Q1), lambda: self.respond(tool=True), self.interrupt,
                            lambda: self.ask(Q1, Q2), lambda: self.respond(first), lambda: self.respond(second)])
            self.assertToolAnswerNeverShared()
            self.assertFalse([a for a in self.answers if a["question"] == Q1])

    def test_two_questions_queued_during_a_tool_and_the_call_recovers(self):
        # Three contexts (Q2, Q3 and the tool's) give three responses; none of them is
        # stored, and once they are answered the call is shared from again.
        self.run_order([lambda: self.ask(Q1), lambda: self.respond(tool=True), lambda: self.ask(Q1, Q2),
                        lambda: self.ask(Q1, Q2, Q3), lambda: self.respond(PRIVATE),
                        lambda: self.respond("Yes, we deliver to Pune on Sundays."),
                        lambda: self.respond("Our hours are on the website."),
                        lambda: self.ask(Q1, Q2, Q3, "What are your opening hours?"),
                        lambda: self.respond("We open 9 to 5.")])
        self.assertToolAnswerNeverShared()
        self.assertEqual(self.store.writes, [("What are your opening hours?", "We open 9 to 5.", False)])

    def test_a_tool_result_after_two_later_turns_is_dropped(self):
        self.run_order([lambda: self.ask(Q1), lambda: self.respond(tool=True), lambda: self.ask(Q1, Q2),
                        lambda: self.respond("We open 9 to 5."), lambda: self.ask(Q1, Q2, Q3),
                        lambda: self.respond("Yes, we deliver to Pune on Sundays."),
                        lambda: self.tool_result_sent_back(Q1), lambda: self.respond(PRIVATE)])
        self.assertToolAnswerNeverShared()
        self.assertEqual(self.store.writes, [(Q3, "Yes, we deliver to Pune on Sundays.", False)])
        self.assertNotIn(PRIVATE, str(self.session.transcript))

    def test_a_tool_with_no_follow_up_never_shifts_later_answers(self):
        steps = lambda result: [  # noqa: E731
            lambda: self.ask(Q1), lambda: self.respond(tool=True),
            *([lambda: self.writeback.process_frame(self.f.FunctionCallResultFrame("{}", run_llm=False), "down")]
              if result else []),
            lambda: self.ask(Q1, Q2), lambda: self.respond("We open 9 to 5."),
            lambda: self.ask(Q1, Q2, Q3), lambda: self.respond("Yes, we deliver to Pune on Sundays."),
        ]
        self.run_order(steps(True))
        self.assertEqual(self.pairs(), [(Q2, "We open 9 to 5.", True), (Q3, "Yes, we deliver to Pune on Sundays.", True)])
        # Without the result frame nothing tells a tool's answer from a caller's while the
        # tool is in flight: Q2's answer is not stored or paired; once the tool is taken as
        # hung, the next turn is stored with its own question.
        self.run_order(steps(False))
        self.assertNotIn((Q2, "We open 9 to 5.", True), self.pairs())
        self.assertFalse([a for a in self.answers if a["question"] == Q2])

    def test_tool_answers_are_kept_to_the_call_in_every_shape(self):
        # One tool, its context sent back up: the answer joins the transcript, privately.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.tool_result_sent_back(Q2),
                        lambda: self.respond("We open 9 to 5 on weekends.")])
        self.assertEqual(self.store.writes, [])
        self.assertEqual(self.session.transcript[-1], {"role": "assistant", "content": "We open 9 to 5 on weekends."})
        # Two tools in one turn, with contexts.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.tool_result_sent_back(Q2),
                        lambda: self.respond(tool=True), lambda: self.tool_result_sent_back(Q2),
                        lambda: self.respond("We open 9 to 5 on weekends."), lambda: self.ask(Q2, Q3),
                        lambda: self.respond("Yes, we deliver to Pune on Sundays.")])
        self.assertEqual(self.pairs(), [(Q2, "We open 9 to 5 on weekends.", False), (Q3, "Yes, we deliver to Pune on Sundays.", True)])
        # Two tools in one turn, no contexts seen.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True), lambda: self.respond(tool=True),
                        lambda: self.respond("We open 9 to 5 on weekends.")])
        self.assertEqual(self.store.writes, [])
        self.assertEqual(self.session.stats()["empty_answers"], 0)
        # The tool frame overtakes the response's start (a system frame in some versions).
        self.run_order([lambda: self.ask(Q2), lambda: self.writeback.process_frame(self.f.FunctionCallsStartedFrame(), "down"),
                        lambda: self.respond(), lambda: self.respond(PRIVATE)])
        self.assertEqual(self.store.writes, [])
        # A tool's context that reaches the gate instead of coming back up.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True),
                        lambda: self.gate.process_frame(self.f.LLMContextFrame(self.tool_context(Q2)), "down"),
                        lambda: self.respond(PRIVATE), lambda: self.ask(Q2, Q3),
                        lambda: self.respond("Yes, we deliver to Pune on Sundays.")])
        self.assertToolAnswerNeverShared()
        self.assertEqual(self.store.writes, [(Q3, "Yes, we deliver to Pune on Sundays.", False)])


    def ten_turns(self):
        steps = []
        for n in range(10):
            question = f"How much is shipping for a parcel of size {'abcdefghij'[n]} to Delhi?"
            steps += [lambda q=question: self.ask(q), lambda n=n: self.respond(f"Shipping costs {n} rupees.")]
        return steps

    def assertStoredAgainWithoutMispairing(self, at_least):
        shipping = [w for w in self.store.writes if w[0].startswith("How much is shipping")]
        self.assertGreaterEqual(len(shipping), at_least)
        for question, answer, _ in shipping:
            self.assertEqual(answer, f"Shipping costs {'abcdefghij'.index(question.split('size ')[1][0])} rupees.")
        for a in self.answers:
            if a["question"].startswith("How much is shipping"):
                self.assertEqual(a["answer"], f"Shipping costs {'abcdefghij'.index(a['question'].split('size ')[1][0])} rupees.")
        self.assertToolAnswerNeverShared()

    def test_a_caller_turn_while_the_tool_runs_does_not_stop_the_call(self):
        tool_calls = lambda: self.respond(tool=True)  # noqa: E731
        sent_back = lambda: self.tool_result_sent_back(Q2)  # noqa: E731
        result = lambda: self.writeback.process_frame(self.f.FunctionCallResultFrame("{}", run_llm=True), "down")  # noqa: E731
        orders = {
            "Q3 asked before the tool's context, Q3 answered first": [
                lambda: self.ask(Q2), tool_calls, lambda: self.ask(Q3), result, sent_back,
                lambda: self.respond("Yes, Sundays too."), lambda: self.respond(PRIVATE)],
            "Q3 asked before the tool's context, the tool answered first": [
                lambda: self.ask(Q2), tool_calls, lambda: self.ask(Q3), result, sent_back,
                lambda: self.respond(PRIVATE), lambda: self.respond("Yes, Sundays too.")],
            "two barge-ins, the tool not cancelled, its context late": [
                lambda: self.ask(Q2), tool_calls, self.interrupt, self.interrupt, lambda: self.ask(Q3),
                sent_back, lambda: self.respond(PRIVATE), lambda: self.respond("Yes, Sundays too.")],
        }
        for name, steps in orders.items():
            with self.subTest(order=name):
                self.run_order(steps + self.ten_turns())
                self.assertStoredAgainWithoutMispairing(10)

    def test_a_tool_that_never_answers_stops_holding_answers(self):
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True)] + self.ten_turns())
        self.assertStoredAgainWithoutMispairing(8)
        # ... and if it answers after all, its result re-arms it: the answer is not shared.
        self.run_order([lambda: self.ask(Q2), lambda: self.respond(tool=True)] + self.ten_turns() + [
            lambda: self.writeback.process_frame(self.f.FunctionCallResultFrame("{}", run_llm=True), "down"),
            lambda: self.respond(PRIVATE)])
        self.assertToolAnswerNeverShared()

    def test_an_empty_tool_result_runs_no_llm_so_later_answers_are_stored(self):
        # Pipecat runs the LLM again only for a non-empty result.
        self.run_order([lambda: self.ask(Q1), lambda: self.respond(tool=True),
                        lambda: self.writeback.process_frame(self.f.FunctionCallResultFrame(""), "down"),
                        lambda: self.ask(Q1, Q2), lambda: self.respond("We open 9 to 5."),
                        lambda: self.ask(Q1, Q2, Q3), lambda: self.respond("Yes, Sundays too.")])
        self.assertEqual(self.store.writes, [(Q2, "We open 9 to 5.", False), (Q3, "Yes, Sundays too.", False)])

    def test_tools_that_never_answer_are_remembered_in_bounded_memory(self):
        steps = []
        for n in range(300):
            question = f"How much is shipping for a parcel of size {n} to Delhi?"
            steps += [lambda q=question: self.ask(q), lambda: self.respond(tool=True)]
        self.run_order(steps)
        self.assertLessEqual(len(self.writeback._pending) + len(self.writeback._hung), 2 * self.pc._MAX_TOOLS)

    def test_a_caller_turn_during_a_slow_settle_keeps_the_llm_order(self):
        """The tool's context and the caller's next turn are queued in the order the LLM
        receives them, even while a held answer is being written or reported slowly."""
        for slow in ("on_answer", "server write"):
            with self.subTest(slow=slow):
                self.setUp()
                llm = []  # contexts in the order the LLM receives them

                def recording(processor):
                    original = processor.push_frame

                    async def push_frame(frame, direction=None):
                        if isinstance(frame, self.f.LLMContextFrame):
                            llm.append(frame.context.messages)
                        await original(frame, direction)
                    processor.push_frame = push_frame

                recording(self.gate)
                recording(self.writeback)
                if slow == "on_answer":
                    async def on_answer(info):
                        await asyncio.sleep(0.3)
                        self.answers.append(info)
                    self.writeback._on_answer = on_answer
                else:
                    cset = self.store.cset

                    def slow_cset(*args, **kwargs):
                        time.sleep(0.3)
                        return cset(*args, **kwargs)
                    self.store.cset = slow_cset

                async def run():
                    await self.ask(Q1)
                    await self.respond(tool=True)  # a tool is in flight
                    await self.ask(Q1, Q2)
                    await self.respond("We open 9 to 5.")  # held while the tool runs
                    sent_back = asyncio.create_task(self.tool_result_sent_back(Q1))
                    await asyncio.sleep(0.05)  # the held answer is being settled
                    await self.ask(Q1, Q2, Q3)
                    await sent_back
                    for messages in llm[-2:]:  # the LLM answers in the order it received
                        tool = any(m.get("role") == "tool" for m in messages)
                        await self.respond(PRIVATE if tool else "Yes, Sundays too.")

                asyncio.run(run())
                self.assertToolAnswerNeverShared()
                self.assertIn((Q3, "Yes, Sundays too.", False), self.store.writes)

    def test_the_audio_cache_keeps_no_clip_for_an_answer_that_was_not_stored(self):
        clips = []
        self.store.ctoolset = lambda tool, key, value, **kw: clips.append(key)
        f = self.f

        async def speak(text):
            for frame in (f.TTSStartedFrame(), f.TTSAudioRawFrame(b"PCM", 16000, 1), f.TTSTextFrame(text),
                          f.TTSStoppedFrame()):
                await self.audio.process_frame(frame, "down")

        async def run():
            await self.ask(Q2)
            await self.respond(tool=True)
            await self.tool_result_sent_back(Q2)
            await self.respond(PRIVATE)  # a tool's answer
            await speak(PRIVATE)
            await self.ask(Q2, Q3)
            await self.respond("Yes, Sundays too.")  # stored: its clip is kept
            await speak("Yes, Sundays too.")

        self.gate, self.writeback, self.audio = self.pc.crowkis_processors(self.session, sample_rate=16000)
        asyncio.run(run())
        _wait_for_audio_stores()  # clips are stored by background workers
        self.assertEqual(len(clips), 1)
        self.assertIn("Yes, Sundays too.", clips[0])
        self.assertNotIn("55123", str(clips))


try:  # the audio-ordering check runs against real Pipecat frames when pipecat-ai is installed
    from pipecat.frames.frames import (
        LLMContextFrame as RealContextFrame,
        LLMFullResponseEndFrame as RealEnd,
        LLMFullResponseStartFrame as RealStart,
        LLMTextFrame as RealText,
        TTSAudioRawFrame as RealAudio,
        TTSSpeakFrame as RealSpeak,
        TTSStartedFrame as RealTTSStarted,
        TTSStoppedFrame as RealTTSStopped,
        TTSTextFrame as RealTTSText,
    )
    from pipecat.processors.aggregators.llm_context import LLMContext as RealContext

    from crowkis.integrations import pipecat as real_pipecat
except ImportError:
    real_pipecat = None


@unittest.skipIf(real_pipecat is None, "pipecat-ai not installed")
class RealPipecatAudioOrderTests(unittest.TestCase):
    """A clip belongs to exactly the TTS run for its own text (real Pipecat frames)."""

    def test_a_cache_hit_during_a_private_answers_speech_never_takes_its_audio(self):
        hit_q, hit_a = "What are your opening hours?", "We open at nine."
        store = Store()
        store.shared[hit_q] = hit_a
        clips = {}
        store.ctoolset = lambda tool, key, value, **kw: clips.__setitem__(key, value)
        session = session_on(store)
        gate, writeback, audio = real_pipecat.crowkis_processors(session, sample_rate=16000)
        spoken = []

        async def keep(frame, direction=None):
            spoken.append(frame)

        for processor in (gate, writeback, audio):
            processor.push_frame = keep

        async def run():
            await gate.process_frame(RealContextFrame(context=RealContext([user("Where is my order?")])), None)
            for frame in (RealStart(), RealText("Your order 55123 for Priya ships Friday."), RealEnd()):
                await writeback.process_frame(frame, None)
            await audio.process_frame(RealTTSStarted(), None)
            await audio.process_frame(RealAudio(b"PRIV", 16000, 1), None)  # the private answer is being spoken
            await gate.process_frame(RealContextFrame(context=RealContext([user(hit_q)])), None)  # a hit, no clip yet
            speak = [f for f in spoken if isinstance(f, RealSpeak)][-1]
            await writeback.process_frame(speak, None)  # in stream order, after the private answer
            for frame in (RealAudio(b"ATE!", 16000, 1), RealTTSStopped()):  # the private answer ends
                await audio.process_frame(frame, None)
            for frame in (RealTTSStarted(), RealAudio(b"HHHH", 16000, 1), RealTTSText(hit_a, "sentence"),
                          RealTTSStopped()):  # the hit is spoken
                await audio.process_frame(frame, None)

        asyncio.run(run())
        decoded = {key: base64.b64decode(value) for key, value in clips.items()}
        self.assertNotIn(b"PRIV", b"".join(decoded.values()))
        self.assertEqual(list(decoded.values()), [b"HHHH"])
        self.assertIn(hit_a, list(decoded)[0])

    def processors(self, store):
        clips = {}
        store.ctoolset = lambda tool, key, value, **kw: clips.__setitem__(key, base64.b64decode(value))
        session = session_on(store)
        spoken = []

        async def on_answer(info):
            return RealSpeak("Sorry, let me check that again.")  # the documented fallback

        gate, writeback, audio = real_pipecat.crowkis_processors(session, sample_rate=16000, on_answer=on_answer)

        async def keep(frame, direction=None):
            spoken.append(frame)

        for processor in (gate, writeback, audio):
            processor.push_frame = keep
        return clips, spoken, gate, writeback, audio

    def test_a_fallback_spoken_from_on_answer_has_its_own_run_and_keeps_no_clip(self):
        hit_q, hit_a = "What are your opening hours?", "We open at nine."
        store = Store()
        store.shared[hit_q] = hit_a
        clips, spoken, gate, writeback, audio = self.processors(store)

        async def run():
            await gate.process_frame(RealContextFrame(context=RealContext([user("Do you deliver on Sundays?")])), None)
            for frame in (RealStart(), RealText("Yes, we deliver on Sundays."), RealEnd()):
                await writeback.process_frame(frame, None)  # stored; on_answer pushes the fallback
            await gate.process_frame(RealContextFrame(context=RealContext([user(hit_q)])), None)
            await writeback.process_frame([f for f in spoken if isinstance(f, RealSpeak)][-1], None)
            for audio_bytes in (b"ANSWER", b"Sorry-AUDIO", b"HIT"):  # three runs, none reporting text
                for frame in (RealTTSStarted(), RealAudio(audio_bytes, 16000, 1), RealTTSStopped()):
                    await audio.process_frame(frame, None)

        asyncio.run(run())
        self.assertNotIn(b"Sorry-AUDIO", b"".join(clips.values()))
        self.assertEqual(clips, {})  # nothing was reported spoken: no new clip is trusted

    def test_a_new_clip_is_kept_only_when_the_tts_reports_its_text(self):
        answer = "Yes, we deliver on Sundays."

        def spoken_with(reported):
            clips, _, gate, writeback, audio = self.processors(Store())

            async def run():
                await gate.process_frame(RealContextFrame(context=RealContext([user("Do you deliver on Sundays?")])), None)
                for frame in (RealStart(), RealText(answer), RealEnd()):
                    await writeback.process_frame(frame, None)
                frames = [RealTTSStarted(), RealAudio(b"PCM", 16000, 1)]
                frames += [RealTTSText(reported, "sentence")] if reported else []
                for frame in frames + [RealTTSStopped()]:
                    await audio.process_frame(frame, None)

            asyncio.run(run())
            return list(clips.values())

        self.assertEqual(spoken_with(None), [])
        self.assertEqual(spoken_with("Something else entirely."), [])
        self.assertEqual(spoken_with(answer), [b"PCM"])

class ReReviewPrivacyTests(unittest.TestCase):

    def assertKeptPrivate(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertFalse(decisions[-1].cacheable, (before, said))
        self.assertTrue(all(said not in query for query, _, _ in store.writes), (said, store.writes))

    def assertShared(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertTrue(decisions[-1].cacheable, said)
        self.assertIn((said, ANSWER, False), store.writes, said)

    def test_rr_03_a_sensitive_state_with_any_first_person_word_stays_private(self):
        for said in (
            "Im pregnant, can i fly",
            "pregnant at 30 weeks, can i fly",
            "pregnant, can i still fly with you",
            "pregnent, can i fly",
            "im allergic to nuts can i eat the curry",
            "allergic to nuts, can i eat the curry",
            "i want to invest my savings, how do i start",
            "what discount do you have for pensioners like me",
            "being a cancer patient do i pay less",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said))
        for said in (
            "Is coffee safe for pregnant women?",
            "What should I do if a doctor is late?",
            "How do I find a good lawyer?",
            "Can I book a tennis court for Sunday?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_rr_04_a_short_turn_after_a_crisis_said_in_words_stays_with_it(self):
        for turns in (
            ("i want to die", "what number do i call"),
            ("i feel like ending my life", "is anyone there"),
            ("i want to kill myself", "nobody cares anyway"),
        ):
            with self.subTest(turns=turns):
                store, _, decisions, seen = call(*turns)
                self.assertIsNone(decisions[-1].messages)
                self.assertFalse(decisions[-1].cacheable)
                self.assertEqual(seen[-1][0], user(turns[0]))
                self.assertTrue(all(turns[-1] not in q for q, _, _ in store.writes))
        self.assertShared("what number do i call", "What are your opening hours?")

    def test_rr_05_names_need_a_person_and_places_brands_festivals_stay_shared(self):
        for said in (
            "Does Mohit have an appointment tomorrow?",
            "Can Priya Sharma pick up the parcel?",
            "Refund status for Rahul Verma",
            "is sanjay's order ready",
            "Dr. Iyer told me to call you",
            "myname is priya",
            "i'm vikram and i want to know the price of the pro plan",
            "can i speak to meera from billing",
            "you are talking to deepak",
            "has Arjun Mehta checked in yet",
            "can priya pick up the order tomorrow",
            "i'm calling for my mother, kamala devi",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said))
        for said in (
            "do you deliver in Hong Kong",
            "do you have a store in San Francisco",
            "how do i get to the Taj Mahal",
            "are trains running on Republic Day",
            "how much is a Big Mac",
            "what is the visa fee for Dubai",
            "are you open for Ramadan",
            "what's Dubai's visa policy",
            "what's the McDonald's breakfast time",
            "what time does the Domino's near the mall close",
            "where is the main branch",
            "what are the main office hours",
            "can i speak to someone in billing",
        ):
            with self.subTest(said=said):
                self.assertShared(said)
        self.assertKeptPrivate("Main order kab aayega?")

    def test_rr_06_ids_addresses_disclosures_and_confirmations_are_private(self):
        for said in (
            "where is ord 7741", "status of #7741 please", "status of AB-7741 please", "is 4409 right",
            "ends in 09", "card number ends with four four", "i'm staying at room 512 of your hotel",
            "deliver to b-204 green park", "i live on elm street", "deliver to house number twelve, mg road",
            "calle mayor 10, madrid", "i think i have covid", "my mother has dementia, can i manage her account",
            "i use a wheelchair, is there a ramp", "my father is on dialysis, can we travel",
            "i'm having a panic attack", "i'm pregnent can i fly",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said))
        for said in ("oui c'est ça", "sim, está certo", "sounds right to me", "uh huh that's it"):
            with self.subTest(said=said):
                self.assertKeptPrivate(said, "can you confirm your details")
        for said in (
            "What happened in 1985?", "Is the 1,499 plan good for families?", "Do you have rooms for 4 people?",
            "Is the store open 24 hours?", "Do you deliver orders above 5000 rupees free?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_merge_outcome_words_agree_with_stored(self):
        session = session_on(Store())
        old = session.decide("What are your opening hours?")
        session.decide("What is the refund policy?")
        late = session._record_model_turn("What are your opening hours?", "Nine to five.", turn=old.turn)
        self.assertEqual(late, "interrupted")
        self.assertIn("moved on", late.why)
        decision = session.answer("Do you deliver on Sundays?", lambda m: "Yes, we do.")
        self.assertTrue(decision.stored)
        self.assertEqual(decision.not_stored, "")
        store, _, decisions, _ = call("Is my order late?")
        self.assertFalse(decisions[-1].stored)
        self.assertTrue(decisions[-1].not_stored)

    def test_rr_07_two_concurrent_decides_never_share_a_turn(self):
        class Slow(VoiceSession):
            """Yields between the turn counter's write and its read, as a busy thread can."""

            @property
            def _turn(self):
                return self.__dict__.get("_turn_value", 0)

            @_turn.setter
            def _turn(self, value):
                self.__dict__["_turn_value"] = value
                time.sleep(0.01)

        session = Slow(Agent("caller", client=Store()), voice="v")
        turns = []
        threads = [
            threading.Thread(target=lambda: turns.append(session.decide("What are your opening hours?").turn))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(sorted(turns), [1, 2])


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
