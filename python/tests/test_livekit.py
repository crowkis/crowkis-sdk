"""CrowkisVoice: Crowkis in a LiveKit Agents agent, ``class Assistant(CrowkisVoice, Agent)``.

Run with real livekit-agents types (Agent, ChatContext, ChatChunk, rtc.AudioFrame); the
agent's LLM and TTS are stand-ins (Agent.default.llm_node / tts_node patched), since there
is no LiveKit room here. A miss reaches the LLM and its answer and audio are kept; the same
question again is spoken from the cache, audio and all, with neither the LLM nor the TTS."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from livekit import rtc
    from livekit.agents import Agent, llm
    from livekit.agents.voice.agent import ModelSettings

    from crowkis.integrations.livekit import CrowkisVoice
except ImportError:  # pragma: no cover - livekit-agents not installed
    Agent = None

from crowkis import Agent as CrowkisAgent, VoiceSession

from test_voice_prompt_guard import PROMPT
from voice_turns_scenarios import SceneStore

QUESTION = "what is your refund policy"
ANSWER = "Refunds take five business days."
PCM = b"\x01\x02" * 640


def _ctx(*turns, instructions="You are Acme's assistant."):
    items = [llm.ChatMessage(role="system", content=[instructions])] if instructions else []
    for role, text in turns:
        items.append(llm.ChatMessage(role=role, content=[text]))
    return llm.ChatContext(items)


class Fakes:
    """Stand-ins for the agent's LLM and TTS (LiveKit's default nodes)."""

    def __init__(self, reply=ANSWER, tool_first=False):
        self.reply = reply
        self.tool_first = tool_first
        self.llm_calls = []
        self.tts_calls = []
        self.tts = SimpleNamespace(sample_rate=16000, num_channels=1, voice="rachel")

    async def llm_node(self, agent, chat_ctx, tools, model_settings):
        self.llm_calls.append([(getattr(i, "role", i.type), getattr(i, "text_content", None)) for i in chat_ctx.items])
        if self.tool_first and not any(i.type == "function_call_output" for i in chat_ctx.items):
            yield llm.ChatChunk(id="c", delta=llm.ChoiceDelta(role="assistant", tool_calls=[
                llm.FunctionToolCall(name="get_weather", arguments="{}", call_id="t1")]))
            return
        for word in self.reply.split(" "):
            yield word + " "

    async def tts_node(self, agent, text, model_settings):
        said = "".join([piece async for piece in text])
        self.tts_calls.append(said)
        for _ in range(2):
            yield rtc.AudioFrame(PCM, 16000, 1, len(PCM) // 2)


def _agent(fakes, store=None, session=None, **kwargs):
    store = store if store is not None else SceneStore()
    session = session or VoiceSession(CrowkisAgent("caller", client=store), voice="v")

    class Assistant(CrowkisVoice, Agent):
        pass

    agent = Assistant(instructions="You are Acme's assistant.", crowkis=session, **kwargs)
    agent._crowkis_tts = lambda: fakes.tts
    return agent, store, session


async def _turn(agent, chat_ctx):
    """One reply: llm_node's text fed to tts_node, as LiveKit does."""
    pieces = []
    async for chunk in agent.llm_node(chat_ctx, [], ModelSettings()):
        pieces.append(chunk if isinstance(chunk, str) else (chunk.delta.content or "" if chunk.delta else ""))

    async def text():
        for piece in pieces:
            yield piece

    frames = [f async for f in agent.tts_node(text(), ModelSettings())]
    return "".join(pieces).strip(), frames


def _patched(fakes):
    return mock.patch.multiple(Agent.default, llm_node=fakes.llm_node, tts_node=fakes.tts_node)


@unittest.skipIf(Agent is None, "livekit-agents not installed")
class LiveKitTests(unittest.TestCase):
    def test_a_miss_then_a_hit_spoken_from_the_cache_with_its_audio(self):
        fakes = Fakes()
        agent, store, _ = _agent(fakes)
        with _patched(fakes):
            said, frames = asyncio.run(_turn(agent, _ctx(("user", QUESTION))))
            self.assertEqual(said, ANSWER)
            self.assertEqual(len(frames), 2)
            again, replayed = asyncio.run(_turn(agent, _ctx(("user", QUESTION), ("assistant", ANSWER), ("user", QUESTION))))
        self.assertEqual(again, ANSWER)
        self.assertEqual(len(fakes.llm_calls), 1)  # the second time, no LLM
        self.assertEqual([t.strip() for t in fakes.tts_calls], [ANSWER])  # nor the TTS: the cached clip was played
        self.assertEqual(b"".join(bytes(f.data) for f in replayed), PCM * 2)
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])
        (key, _), = store.tool_writes
        self.assertEqual(key["format"], "pcm16-16000")

    def test_the_model_reads_the_instructions_and_only_the_question(self):
        fakes = Fakes()
        agent, _, _ = _agent(fakes)
        with _patched(fakes):
            asyncio.run(_turn(agent, _ctx(("user", "I am Priya, account 4471."), ("assistant", "Hello Priya."),
                                          ("user", QUESTION))))
        self.assertEqual(fakes.llm_calls[0], [("system", "You are Acme's assistant."), ("user", QUESTION)])

    def test_a_personal_turn_reads_the_whole_call_and_is_never_shared(self):
        fakes = Fakes(reply="Order 48213 left the depot this morning.")
        agent, store, _ = _agent(fakes)
        with _patched(fakes):
            asyncio.run(_turn(agent, _ctx(("user", "my order 48213 has not arrived where is it"))))
        self.assertEqual(store.writes, [])
        self.assertEqual(store.tool_writes, [])

    def test_an_answer_built_from_a_tool_stays_in_the_call(self):
        fakes = Fakes(reply="It is sunny in Paris.", tool_first=True)
        agent, store, session = _agent(fakes)
        question = "what is the weather in paris today"
        with _patched(fakes):
            asyncio.run(_turn(agent, _ctx(("user", question))))  # the tool call
            tool_ctx = _ctx(("user", question))
            tool_ctx.items.append(llm.FunctionCall(call_id="t1", name="get_weather", arguments="{}"))
            tool_ctx.items.append(llm.FunctionCallOutput(call_id="t1", name="get_weather", output="sunny",
                                                         is_error=False))
            said, _ = asyncio.run(_turn(agent, tool_ctx))
        self.assertEqual(said, "It is sunny in Paris.")
        self.assertEqual(store.writes, [])
        self.assertEqual(store.tool_writes, [])
        self.assertEqual(session.transcript[-1]["content"], "It is sunny in Paris.")

    def test_a_reply_livekit_cancels_is_never_saved(self):
        fakes = Fakes(reply="Refunds take five business days to reach your card.")
        agent, store, _ = _agent(fakes)

        async def run():
            stream = agent.llm_node(_ctx(("user", QUESTION)), [], ModelSettings())
            await stream.__anext__()
            await stream.aclose()  # the caller interrupted

        with _patched(fakes):
            asyncio.run(run())
        self.assertEqual(store.writes, [])

    def test_an_answer_repeating_a_caller_detail_from_the_instructions_stays_private(self):
        fakes = Fakes(reply="Hi Asha! We open at nine.")
        agent, store, _ = _agent(fakes)
        with _patched(fakes):
            asyncio.run(_turn(agent, _ctx(("user", "what are your opening hours"), instructions=PROMPT)))
        self.assertEqual(store.writes, [])

    def test_a_say_greeting_never_lands_under_an_answer(self):
        fakes = Fakes()
        agent, store, _ = _agent(fakes)

        async def run():
            async for _ in agent.llm_node(_ctx(("user", QUESTION)), [], ModelSettings()):
                pass

            async def greeting():
                yield "Welcome to Acme!"

            async for _ in agent.tts_node(greeting(), ModelSettings()):  # session.say(...)
                pass

        with _patched(fakes):
            asyncio.run(run())
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])
        self.assertEqual(store.tool_writes, [])  # the greeting's audio was not kept as the answer's

    def test_the_voice_comes_from_the_tts_when_the_session_has_none(self):
        import crowkis

        fakes = Fakes()
        store = SceneStore()
        session = crowkis.voice_session(client=store)
        agent, _, _ = _agent(fakes, store=store, session=session)
        with _patched(fakes):
            asyncio.run(_turn(agent, _ctx(("user", QUESTION))))
        self.assertEqual(session.voice, "rachel")
        (key, _), = store.tool_writes
        self.assertEqual(key["voice"], "rachel")

    def test_with_no_crowkis_given_a_voice_session_is_made(self):
        class Assistant(CrowkisVoice, Agent):
            crowkis_options = {"client": SceneStore(), "agent_id": "support"}

        agent = Assistant(instructions="x")
        self.assertEqual(agent.crowkis.session.agent.agent_id, "support")
        self.assertEqual(agent.crowkis.session.latency_budget_ms, 250)


class FakeSpeech:
    """A LiveKit SpeechHandle as the nodes see it: scheduled, or a preemptive attempt that
    LiveKit then keeps or discards."""

    def __init__(self, speech_id, scheduled=True, discard=False):
        self.id = speech_id
        self.scheduled = scheduled
        self.interrupted = False
        self._discard = discard

    async def _wait_for_scheduled(self):
        await asyncio.sleep(0)

    async def wait_if_not_interrupted(self, aw):
        await asyncio.gather(*aw)
        if self._discard:
            self.interrupted = True  # the caller kept talking: LiveKit dropped this attempt
        else:
            self.scheduled = True


def _in_speech(handle, coro_fn):
    from livekit.agents.voice.agent_activity import _SpeechHandleContextVar

    async def run():
        _SpeechHandleContextVar.set(handle)
        return await coro_fn()

    return asyncio.run(run())


@unittest.skipIf(Agent is None, "livekit-agents not installed")
class LiveKitFlowTests(unittest.TestCase):
    def test_generate_reply_with_instructions_is_not_a_caller_turn(self):
        fakes = Fakes(reply="Goodbye, thanks for calling!")
        agent, store, session = _agent(fakes)
        ctx = _ctx(("user", QUESTION), ("assistant", ANSWER))
        ctx.items.append(llm.ChatMessage(role="system", content=["Say goodbye to the caller."]))
        with _patched(fakes):
            said, _ = asyncio.run(_turn(agent, ctx))
        self.assertEqual(said, "Goodbye, thanks for calling!")
        self.assertEqual(fakes.llm_calls[0][-1], ("system", "Say goodbye to the caller."))  # whole context
        self.assertEqual(session.stats()["turns"], 0)  # nothing decided
        self.assertEqual(store.writes, [])

    def test_a_preemptive_attempt_livekit_discards_is_never_saved(self):
        fakes = Fakes()
        agent, store, session = _agent(fakes)
        with _patched(fakes):
            _in_speech(FakeSpeech("s1", scheduled=False, discard=True),
                       lambda: _turn(agent, _ctx(("user", "what time do you"))))
        self.assertEqual(store.writes, [])
        self.assertEqual(session.transcript, [])

    def test_a_preemptive_attempt_livekit_keeps_is_saved(self):
        fakes = Fakes()
        agent, store, _ = _agent(fakes)
        with _patched(fakes):
            _in_speech(FakeSpeech("s1", scheduled=False), lambda: _turn(agent, _ctx(("user", QUESTION))))
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    def test_a_discarded_cache_hit_is_rolled_back(self):
        fakes = Fakes()
        store = SceneStore({QUESTION: ANSWER})
        agent, _, session = _agent(fakes, store=store)
        with _patched(fakes):
            said, _ = _in_speech(FakeSpeech("s1", scheduled=False, discard=True),
                                 lambda: _turn(agent, _ctx(("user", QUESTION))))
        self.assertEqual(said, ANSWER)
        self.assertEqual(session.transcript, [])

    def test_a_say_never_plays_another_replys_cached_audio(self):
        fakes = Fakes()
        store = SceneStore({QUESTION: ANSWER})
        agent, _, _ = _agent(fakes, store=store)

        async def run():
            from livekit.agents.voice.agent_activity import _SpeechHandleContextVar

            # Reply s1 is a hit whose audio Crowkis has; its tts never runs (interrupted).
            agent._crowkis_clip_cache()
            store.tool[agent._crowkis_clip_cache()._key(ANSWER)] = __import__("base64").b64encode(PCM).decode()
            _SpeechHandleContextVar.set(FakeSpeech("s1"))
            async for _ in agent.llm_node(_ctx(("user", QUESTION)), [], ModelSettings()):
                pass
            # Then a say() runs under its own speech: it is synthesised, not given s1's clip.
            _SpeechHandleContextVar.set(FakeSpeech("s2"))

            async def line():
                yield "Are you still there?"

            return [f async for f in agent.tts_node(line(), ModelSettings())]

        with _patched(fakes):
            asyncio.run(run())
        self.assertEqual([t.strip() for t in fakes.tts_calls], ["Are you still there?"])

    def test_a_reply_cancelled_while_written_saves_nothing_and_frees_its_run(self):
        fakes = Fakes()
        agent, store, _ = _agent(fakes)

        async def slow_llm(agent_, chat_ctx, tools, model_settings):
            yield "Refunds "
            await asyncio.sleep(10)
            yield "take five days."

        async def run():
            async def consume():
                async for _ in agent.llm_node(_ctx(("user", QUESTION)), [], ModelSettings()):
                    pass

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with mock.patch.multiple(Agent.default, llm_node=slow_llm, tts_node=fakes.tts_node):
            asyncio.run(run())
        self.assertEqual(store.writes, [])
        self.assertEqual(list(agent._crowkis_clip_cache()._runs), [])

    def test_rag_context_or_a_running_tool_means_the_whole_context_and_no_sharing(self):
        for name, add in (
            ("rag", lambda ctx: ctx.items.insert(len(ctx.items) - 1, llm.ChatMessage(
                role="system", content=["Knowledge: refunds for Gold members take 2 days."]))),
            ("running tool", lambda ctx: ctx.items.insert(len(ctx.items) - 1, llm.FunctionCall(
                call_id="t9", name="book", arguments="{}", extra={"__lk_running_placeholder__": True}))),
        ):
            with self.subTest(name):
                fakes = Fakes(reply="Refunds take 2 days for Gold members.")
                agent, store, session = _agent(fakes)
                ctx = _ctx(("user", QUESTION))
                add(ctx)
                with _patched(fakes):
                    asyncio.run(_turn(agent, ctx))
                self.assertEqual(len(fakes.llm_calls[0]), len(ctx.items))  # the model read it all
                self.assertEqual(store.writes, [])
                self.assertEqual(session.transcript[-1]["content"], "Refunds take 2 days for Gold members.")

    def test_history_or_a_rag_turn_that_tells_the_call_something_keeps_the_rest_private(self):
        told = "I'm planning a trip to Goa in December."
        later = "What should I pack?"
        rag = lambda ctx: ctx.items.insert(len(ctx.items) - 1, llm.ChatMessage(
            role="system", content=["Knowledge: Goa is warm in December."]))
        for name, contexts in (
            # the app's own chat history, never seen by Crowkis
            ("history", [_ctx(("user", told), ("assistant", "Lovely!"), ("user", later))]),
            # the turn was answered with RAG data (kept to the call), then a plain question
            ("rag turn", [_ctx(("user", told)), _ctx(("user", told), ("assistant", "Lovely!"), ("user", later))]),
        ):
            with self.subTest(name):
                fakes = Fakes(reply="Light cotton and a light jacket.")
                agent, store, _ = _agent(fakes, store=SceneStore({later: "Light clothes."}))
                if name == "rag turn":
                    rag(contexts[0])
                with _patched(fakes):
                    for ctx in contexts:
                        asyncio.run(_turn(agent, ctx))
                self.assertEqual(len(fakes.llm_calls), len(contexts), "never served from the shared cache")
                self.assertEqual(len(fakes.llm_calls[-1]), len(contexts[-1].items), "the model read it all")
                self.assertEqual((store.writes, store.tool_writes), ([], []))

    def test_plain_history_keeps_the_shared_cache(self):
        fakes = Fakes()
        agent, _, _ = _agent(fakes, store=SceneStore({"What should I pack?": "Light clothes."}))
        with _patched(fakes):
            said, _ = asyncio.run(_turn(agent, _ctx(("user", "Hi, I have a question."), ("assistant", "Sure."),
                                                    ("user", "What should I pack?"))))
        self.assertEqual(said, "Light clothes.")
        self.assertEqual(fakes.llm_calls, [])

    def test_the_voice_follows_a_tts_voice_change(self):
        import crowkis

        fakes = Fakes()
        store = SceneStore()
        session = crowkis.voice_session(client=store)
        agent, _, _ = _agent(fakes, store=store, session=session)
        with _patched(fakes):
            asyncio.run(_turn(agent, _ctx(("user", QUESTION))))
            fakes.tts.voice = "nova"
            asyncio.run(_turn(agent, _ctx(("user", "how do I reset my password"))))
        self.assertEqual(session.voice, "nova")
        self.assertEqual([k["voice"] for k, _ in store.tool_writes], ["rachel", "nova"])

    def test_class_options_are_not_shared_between_agents(self):
        self.assertIsNone(CrowkisVoice.crowkis_options)


if __name__ == "__main__":
    unittest.main()
