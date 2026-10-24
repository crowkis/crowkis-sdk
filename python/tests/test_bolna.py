"""CrowkisLLM: Crowkis in a Bolna agent (``crowkis.integrations.bolna``).

Bolna builds one LLM and one TaskManager per call and picks the LLM class by name from
``bolna.providers.SUPPORTED_LLM_PROVIDERS``. ``register_crowkis()`` adds a provider that
wraps one of Bolna's own LLM classes (a Decorator): a caller's question is answered from
the cache when it can be, otherwise the wrapped LLM answers and its answer is kept once
Bolna has really sent it, so a reply trimmed by a barge-in is never saved.

These tests run the real Bolna types (``LLMStreamChunk``, ``BaseLLM``, ``ConversationHistory``)
and a real VoiceSession over a fake cache; the model is a stand-in. They need no server."""

import asyncio
import base64
import contextlib
import copy
import gc
import json
import os
import unittest
from unittest import mock
import weakref
from collections import Counter
from types import SimpleNamespace

import pytest

pytest.importorskip("bolna")

from bolna import providers as bolna_providers  # noqa: E402
from bolna.helpers.conversation_history import ConversationHistory  # noqa: E402
from bolna.llms.llm import BaseLLM  # noqa: E402
from bolna.helpers.utils import create_ws_data_packet  # noqa: E402
from bolna.llms.types import LatencyData, LLMStreamChunk  # noqa: E402
from bolna.synthesizer.base_synthesizer import BaseSynthesizer  # noqa: E402

from crowkis import Agent, AsyncVoiceSession, CrowkisError, VoiceSession  # noqa: E402
from crowkis.agent import _tts_key, _wait_for_audio_stores  # noqa: E402
from crowkis.integrations.bolna import CrowkisBolnaError, CrowkisLLM, CrowkisSynthesizer, register_crowkis  # noqa: E402
from crowkis.integrations.bolna.synthesizer import CallLinks  # noqa: E402
from crowkis.voice import _reset_prompt_baselines  # noqa: E402

from test_voice_prompt_guard import PROMPT  # noqa: E402
from voice_turns_scenarios import SceneStore  # noqa: E402

SYSTEM = "You are Acme's assistant."
QUESTION = "what is your refund policy"
ANSWER = "Refunds take five business days."
LONG_ANSWER = "Refunds take five business days to reach your card and we also send a confirmation email once it is done."
PERSONAL = "my order number is 48213, where is it?"
PERSONAL_ANSWER = "Order 48213 left the depot this morning."
BUFFER = 40
FAKE_BASE = "crowkis-test-fake-base"


# --- stand-ins ------------------------------------------------------------------------------


class FakeInner(BaseLLM):
    """A Bolna LLM that records what it was asked and streams a scripted answer."""

    def __init__(self, reply=ANSWER, *, function_call=False, fail_after_first=False, gate=False,
                 empty_end_marker=False, **kwargs):
        super().__init__(max_tokens=kwargs.get("max_tokens", 100), buffer_size=BUFFER)
        self.model = "fake"
        self.reply = reply
        self.function_call = function_call
        self.fail_after_first = fail_after_first
        self.gate = asyncio.Event() if gate else None
        self.paused = asyncio.Event()
        self.empty_end_marker = empty_end_marker
        self.calls = []
        self.chain_resets = 0
        self.cancelled_in_flight = 0
        self.closed = 0
        self.hints = []
        self.scripted = []

    def pieces(self):
        words = self.reply.split()
        return [" ".join(words[i:i + 3]) for i in range(0, len(words), 3)] or [""]

    async def generate_stream(self, messages, synthesize=True, request_json=False, meta_info=None,
                              tool_choice=None, tools=None):
        self.calls.append(dict(messages=messages, synthesize=synthesize, request_json=request_json,
                               meta_info=meta_info, tool_choice=tool_choice, tools=tools))
        self.scripted = []
        sequence_id = (meta_info or {}).get("sequence_id")
        pieces = self.pieces()
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1 and not self.function_call and not self.empty_end_marker
            chunk = LLMStreamChunk(data=piece, end_of_stream=last, latency=LatencyData(sequence_id=sequence_id))
            self.scripted.append(chunk)
            yield chunk
            if index == 0 and self.fail_after_first:
                raise RuntimeError("provider down")
            if index == 0 and self.gate is not None:
                self.paused.set()
                await self.gate.wait()
        if self.function_call:
            chunk = LLMStreamChunk(data=None, end_of_stream=True, is_function_call=True, function_name="get_weather")
            self.scripted.append(chunk)
            yield chunk
        elif self.empty_end_marker:
            chunk = LLMStreamChunk(data="", end_of_stream=True, latency=LatencyData(sequence_id=sequence_id))
            self.scripted.append(chunk)
            yield chunk

    async def generate(self, messages, stream=True, ret_metadata=False):
        return "generated"

    async def route(self, messages, tools, tool_choice="required", meta_info=None):
        return {"function_name": "next_node"}

    async def trigger_function_call(self, *args, **kwargs):
        return "triggered"

    def invalidate_response_chain(self):
        self.chain_resets += 1

    def set_interruption_hint(self, heard_text):
        self.hints.append(heard_text)

    def cancel_in_flight_response(self):
        self.cancelled_in_flight += 1

    async def close(self):
        self.closed += 1


class FakeTaskManager:
    """What the adapter reads of Bolna's TaskManager: the history and the task config."""

    def __init__(self, agent_type="simple_llm_agent"):
        self.conversation_history = ConversationHistory([])
        llm_agent = {} if agent_type is None else {"agent_type": agent_type}
        self.task_config = {"tools_config": {"llm_agent": llm_agent}}

    @property
    def history(self):
        return self.conversation_history.messages

    def commit(self, response_uid, text):
        """Bolna's commit of a reply to the real history once its audio was sent."""
        self.conversation_history.append_assistant(text, response_uid=response_uid, turn_id=1)


def make_session(store):
    return AsyncVoiceSession.wrap(VoiceSession(Agent("caller", client=store), voice="v"))


def meta(sequence_id=1, response_uid="r1", **extra):
    return {"sequence_id": sequence_id, "origin": "transcriber", "response_uid": response_uid, **extra}


def user_turn(text, system=SYSTEM, history=()):
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]


def text_of(chunks):
    return " ".join(" ".join(str(chunk.data or "").split()) for chunk in chunks).strip()


class Call:
    """One phone call: its own session, inner LLM and task manager over a (shared) cache."""

    def __init__(self, store, reply=ANSWER, *, task_manager=True, session=None, **inner_options):
        self.store = store
        self.session = session or make_session(store)
        self.inner = FakeInner(reply, **inner_options)
        self.tm = FakeTaskManager() if task_manager is True else (task_manager or None)
        self.llm = CrowkisLLM(self.inner, self.session, task_manager=self.tm)
        self.sequence = 0

    async def stream(self, messages, *, synthesize=True, meta_info="default", **kwargs):
        self.sequence += 1
        if meta_info == "default":
            meta_info = meta(self.sequence, f"r{self.sequence}")
        return [chunk async for chunk in self.llm.generate_stream(
            messages, synthesize=synthesize, meta_info=meta_info, **kwargs)]

    async def turn(self, text, *, committed=True, history=(), system=SYSTEM, synthesize=True):
        """A caller turn. ``committed``: Bolna sent the reply and wrote it to its history in full."""
        chunks = await self.stream(user_turn(text, system, history), synthesize=synthesize)
        if committed and self.tm is not None:
            self.tm.commit(f"r{self.sequence}", text_of(chunks))
        return chunks

    async def end(self):
        await self.llm.close()

    def saved(self):
        return [write[:2] for write in self.store.writes if not write[2]]


class BoundSession:
    """Delegates to a real session but raises from the named calls."""

    def __init__(self, real, *, decide=False, record=False):
        self._real, self._decide, self._record = real, decide, record

    async def decide(self, caller_said):
        if self._decide:
            raise RuntimeError("crowkis lookup exploded")
        return await self._real.decide(caller_said)

    async def record(self, decision, answer, **kwargs):
        if self._record:
            raise RuntimeError("crowkis write exploded")
        return await self._real.record(decision, answer, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_prompt_baselines()  # each test starts with no remembered system prompts

    def calls_of(self, *calls):
        return [len(call.inner.calls) for call in calls]


# --- registration ---------------------------------------------------------------------------


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self._providers_before = dict(bolna_providers.SUPPORTED_LLM_PROVIDERS)

        class FakeBase(FakeInner):
            def __init__(inner_self, **kwargs):
                super().__init__(reply=ANSWER)
                inner_self.kwargs = kwargs
                inner_self.model = kwargs.get("model")

        self.fake_base = FakeBase
        bolna_providers.SUPPORTED_LLM_PROVIDERS[FAKE_BASE] = FakeBase

    def tearDown(self):
        bolna_providers.SUPPORTED_LLM_PROVIDERS.clear()
        bolna_providers.SUPPORTED_LLM_PROVIDERS.update(self._providers_before)

    def test_the_provider_is_added_under_its_name(self):
        cls = register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: None)
        self.assertIs(bolna_providers.SUPPORTED_LLM_PROVIDERS["crowkis-test"], cls)
        self.assertTrue(issubclass(cls, CrowkisLLM))
        self.assertIs(bolna_providers.SUPPORTED_LLM_PROVIDERS[FAKE_BASE], self.fake_base)  # the base is untouched

    def test_the_default_provider_wraps_bolnas_openai_llm(self):
        cls = register_crowkis()
        self.assertTrue(issubclass(cls, CrowkisLLM))
        self.assertIs(bolna_providers.SUPPORTED_LLM_PROVIDERS["crowkis"], cls)
        self.assertIn("openai", bolna_providers.SUPPORTED_LLM_PROVIDERS)

    def test_registering_twice_is_fine(self):
        register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: None)
        again = register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: None)
        self.assertTrue(issubclass(again, CrowkisLLM))
        self.assertIs(bolna_providers.SUPPORTED_LLM_PROVIDERS["crowkis-test"], again)

    def test_an_unknown_base_is_refused(self):
        with self.assertRaises(CrowkisBolnaError):
            register_crowkis(name="crowkis-test", base="no-such-llm")
        self.assertNotIn("crowkis-test", bolna_providers.SUPPORTED_LLM_PROVIDERS)

    def test_a_provider_cannot_wrap_itself(self):
        with self.assertRaises(CrowkisBolnaError):
            register_crowkis(name=FAKE_BASE, base=FAKE_BASE)
        self.assertIs(bolna_providers.SUPPORTED_LLM_PROVIDERS[FAKE_BASE], self.fake_base)

    def test_the_error_is_a_crowkis_error(self):
        self.assertTrue(issubclass(CrowkisBolnaError, CrowkisError))

    def test_bolnas_task_manager_sees_the_provider(self):
        from bolna.agent_manager import task_manager as tm

        self.assertIs(tm.SUPPORTED_LLM_PROVIDERS, bolna_providers.SUPPORTED_LLM_PROVIDERS)
        register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: None)
        self.assertIn("crowkis-test", tm.SUPPORTED_LLM_PROVIDERS)

    def test_the_class_builds_as_bolna_builds_it(self):
        task_manager = FakeTaskManager()
        session = make_session(SceneStore())
        cls = register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: session)
        llm = cls(language="en", model="gpt-4o-mini", max_tokens=150, provider="crowkis", temperature=0.2,
                  task_manager_instance=task_manager)
        self.assertIsInstance(llm, CrowkisLLM)
        self.assertEqual(llm.kwargs["provider"], FAKE_BASE)  # the inner is built as its own provider
        self.assertEqual(llm.kwargs["model"], "gpt-4o-mini")
        self.assertEqual(llm.kwargs["max_tokens"], 150)
        self.assertEqual(llm.kwargs["temperature"], 0.2)
        self.assertEqual(llm.kwargs["language"], "en")
        self.assertEqual(llm.model, "gpt-4o-mini")

    def test_each_instance_gets_its_own_session(self):
        made = []

        def factory():
            made.append(make_session(SceneStore()))
            return made[-1]

        cls = register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=factory)
        cls(language="en", model="m", provider="crowkis")
        cls(language="en", model="m", provider="crowkis")
        self.assertEqual(len(made), 2)
        self.assertIsNot(made[0], made[1])

    def test_without_a_factory_the_session_is_built_from_the_options(self):
        store = SceneStore()
        cls = register_crowkis(name="crowkis-test", base=FAKE_BASE, session_options={"client": store})
        task_manager = FakeTaskManager()
        llm = cls(language="en", model="m", provider="crowkis", task_manager_instance=task_manager)

        async def run():
            chunks = [c async for c in llm.generate_stream(user_turn(QUESTION), meta_info=meta())]
            task_manager.commit("r1", text_of(chunks))
            await llm.close()
            return chunks

        chunks = asyncio.run(run())
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])  # saved once Bolna committed it


# --- delegation -----------------------------------------------------------------------------


class DelegationTests(Base):
    async def test_attributes_and_untouched_calls_reach_the_inner_llm(self):
        call = Call(SceneStore())
        self.assertEqual(call.llm.model, "fake")
        self.assertEqual(await call.llm.generate([]), "generated")
        self.assertEqual(await call.llm.route([], []), {"function_name": "next_node"})
        self.assertEqual(await call.llm.trigger_function_call(), "triggered")
        call.llm.set_interruption_hint("Refunds take")
        self.assertEqual(call.inner.hints, ["Refunds take"])
        call.llm.invalidate_response_chain()
        self.assertEqual(call.inner.chain_resets, 1)
        await call.llm.close()
        self.assertEqual(call.inner.closed, 1)

    async def test_generate_and_route_are_never_cached(self):
        store = SceneStore({QUESTION: ANSWER})
        call = Call(store)
        self.assertEqual(await call.llm.generate(user_turn(QUESTION)), "generated")
        await call.end()
        self.assertEqual(store.writes, [])
        self.assertEqual(call.session.stats()["turns"], 0)

    async def test_cancelling_the_response_cancels_the_crowkis_turn_too(self):
        call = Call(SceneStore())
        stream = call.llm.generate_stream(user_turn(QUESTION), meta_info=meta())
        await stream.__anext__()
        call.llm.cancel_in_flight_response()
        self.assertEqual(call.inner.cancelled_in_flight, 1)
        async for _ in stream:
            pass
        call.tm.commit("r1", ANSWER)
        await call.end()
        self.assertEqual(call.store.writes, [])
        self.assertEqual(call.session.stats()["barge_ins"], 1)


# --- the main flow --------------------------------------------------------------------------


class FlowTests(Base):
    async def test_a_miss_streams_the_inner_answer_unchanged(self):
        call = Call(SceneStore())
        chunks = await call.stream(user_turn(QUESTION))
        self.assertEqual(chunks, call.inner.scripted)
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(len(call.inner.calls), 1)

    async def test_the_answer_is_saved_once_bolna_has_committed_it(self):
        store = SceneStore()
        call = Call(store)
        await call.turn(QUESTION)
        self.assertEqual(store.writes, [])  # still pending: Bolna may yet trim it
        await call.end()
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    async def test_the_answer_is_settled_when_the_next_turn_starts(self):
        store = SceneStore()
        call = Call(store)
        await call.turn(QUESTION)
        await call.turn("what are your opening hours")
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])  # the second answer is still pending

    async def test_another_call_asking_the_same_question_is_served_without_its_llm(self):
        store = SceneStore()
        first = Call(store)
        await first.turn(QUESTION)
        await first.end()
        second = Call(store, reply="This must never be said.")
        chunks = await second.turn(QUESTION)
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(second.inner.calls, [])
        self.assertEqual(second.inner.chain_resets, 1)
        self.assertTrue(chunks[-1].end_of_stream)

    async def test_a_final_empty_end_marker_does_not_change_the_saved_answer(self):
        store = SceneStore()
        call = Call(store, empty_end_marker=True)
        await call.turn(QUESTION)
        await call.end()
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    async def test_a_question_nobody_cached_is_a_miss_for_another_call(self):
        store = SceneStore({"what are your opening hours": "We open at nine."})
        call = Call(store)
        await call.turn(QUESTION)
        self.assertEqual(len(call.inner.calls), 1)


# --- a served answer ------------------------------------------------------------------------


class HitChunkTests(Base):
    async def hit(self, text=LONG_ANSWER, question=QUESTION, **kwargs):
        call = Call(SceneStore({question: text}))
        chunks = await call.stream(user_turn(question), meta_info=meta(sequence_id=7), **kwargs)
        return call, chunks

    async def test_synthesized_text_comes_in_buffer_sized_pieces_on_word_boundaries(self):
        call, chunks = await self.hit(synthesize=True)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(chunk.data.strip() for chunk in chunks), LONG_ANSWER)
        words = set(LONG_ANSWER.split())
        for chunk in chunks:
            self.assertLessEqual(len(chunk.data), BUFFER * 2)  # about buffer_size
            self.assertTrue(set(chunk.data.split()) <= words, chunk.data)  # never mid-word
        self.assertEqual([c.end_of_stream for c in chunks], [False] * (len(chunks) - 1) + [True])
        self.assertEqual(call.inner.calls, [])

    async def test_unsynthesized_text_is_one_chunk(self):
        call, chunks = await self.hit(synthesize=False)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].data, LONG_ANSWER)
        self.assertTrue(chunks[0].end_of_stream)
        self.assertEqual(call.inner.calls, [])

    async def test_every_chunk_carries_the_sequence_id(self):
        for synthesize in (True, False):
            with self.subTest(synthesize=synthesize):
                _, chunks = await self.hit(synthesize=synthesize)
                for chunk in chunks:
                    self.assertIsInstance(chunk.latency, LatencyData)
                    self.assertEqual(chunk.latency.sequence_id, 7)
                    self.assertFalse(chunk.is_function_call)

    async def test_the_response_chain_is_reset_after_a_served_answer(self):
        call, _ = await self.hit()
        self.assertEqual(call.inner.chain_resets, 1)

    async def test_a_short_answer_is_one_piece(self):
        _, chunks = await self.hit(ANSWER)
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertTrue(chunks[-1].end_of_stream)

    async def test_a_served_answer_is_not_saved_again(self):
        store = SceneStore({QUESTION: ANSWER})
        call = Call(store)
        await call.turn(QUESTION)
        await call.end()
        self.assertEqual(store.writes, [])

    async def test_a_hit_for_a_hinglish_question_is_served(self):
        question = "refund kitne din mein milta hai"
        call, chunks = await self.hit("Paanch din mein.", question)
        self.assertEqual(text_of(chunks), "Paanch din mein.")
        self.assertEqual(call.inner.calls, [])


# --- what the model reads -------------------------------------------------------------------


class ContextTests(Base):
    async def test_the_model_reads_the_system_prompt_and_only_the_question(self):
        call = Call(SceneStore())
        history = [{"role": "user", "content": "I am Priya, account 4471."},
                   {"role": "assistant", "content": "Hello Priya."}]
        await call.turn(QUESTION, history=history)
        self.assertEqual(call.inner.calls[0]["messages"],
                         [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}])
        self.assertEqual(call.inner.chain_resets, 1)  # the narrowed context breaks any response chain

    async def test_a_personal_turn_reads_the_whole_call_and_is_never_shared(self):
        store = SceneStore()
        call = Call(store, reply=PERSONAL_ANSWER)
        messages = user_turn(PERSONAL)
        chunks = await call.stream(messages)
        self.assertEqual(call.inner.calls[0]["messages"], messages)
        self.assertEqual(text_of(chunks), PERSONAL_ANSWER)
        call.tm.commit("r1", PERSONAL_ANSWER)
        await call.end()
        self.assertEqual(store.writes, [])
        self.assertEqual(store.tool_writes, [])
        other = Call(store, reply="Please call back later.")
        await other.turn(PERSONAL)
        self.assertEqual(len(other.inner.calls), 1)  # a miss: nothing from the first call was kept

    async def test_a_full_context_call_leaves_the_response_chain_alone(self):
        call = Call(SceneStore(), reply=PERSONAL_ANSWER)
        await call.stream(user_turn(PERSONAL))
        self.assertEqual(call.inner.chain_resets, 0)

    async def test_a_detail_told_earlier_keeps_later_answers_private(self):
        store = SceneStore()
        call = Call(store, reply="Order 48213 is out for delivery.")
        await call.turn(PERSONAL, committed=True)
        again = await call.turn(QUESTION, history=[{"role": "user", "content": PERSONAL}])
        self.assertEqual(text_of(again), "Order 48213 is out for delivery.")
        await call.end()
        self.assertEqual(store.writes, [])


# --- turns Crowkis never touches ------------------------------------------------------------


def _tool_messages():
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": QUESTION},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function",
                                                                  "function": {"name": "weather", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "sunny"}]


BYPASS_CASES = [
    ("a tool's follow-up", dict(messages=_tool_messages(), meta_info=meta())),
    ("a follow-up to a parent response", dict(messages=user_turn(QUESTION), meta_info=meta(parent_response_uid="p1"))),
    ("an eager end-of-turn guess", dict(messages=user_turn(QUESTION), meta_info=meta(eager_eot=True))),
    ("a dtmf origin", dict(messages=user_turn(QUESTION), meta_info=meta(origin="dtmf"))),
    ("sequence id -1", dict(messages=user_turn(QUESTION), meta_info=meta(sequence_id=-1))),
    ("a silence nudge", dict(messages=user_turn("[silence] are you still there"), meta_info=meta())),
    ("a JSON request", dict(messages=user_turn(QUESTION), meta_info=meta(), request_json=True)),
    ("tools offered with a forced choice", dict(messages=_tool_messages(), meta_info=meta(), tool_choice="required",
                                                tools=[{"type": "function", "function": {"name": "weather"}}])),
]
AGENT_TYPE_CASES = ["graph_agent", "knowledgebase_agent"]


class BypassTests(Base):
    """Seeded with the question so that, were it decided, it would be served from the cache."""

    def bypass_call(self, **options):
        return Call(SceneStore({QUESTION: ANSWER}), reply="The model's own words.", **options)

    async def assert_bypassed(self, call, kwargs):
        original = dict(synthesize=True, request_json=False, meta_info=None, tool_choice=None, tools=None)
        original.update(kwargs)
        expected = {key: (list(value) if key == "messages" else value) for key, value in original.items()}
        chunks = await call.stream(original.pop("messages"), **original)
        self.assertEqual(len(call.inner.calls), 1)
        self.assertEqual(call.inner.calls[0], expected)
        self.assertEqual(chunks, call.inner.scripted)
        self.assertEqual(call.inner.chain_resets, 0)
        if call.tm is not None:
            call.tm.commit("r1", text_of(chunks))
        await call.end()
        self.assertEqual(call.store.writes, [])
        self.assertEqual(call.store.tool_writes, [])
        self.assertEqual(call.session.stats()["turns"], 0)  # never decided

    async def test_each_bypass_rule_hands_the_turn_to_the_inner_llm_untouched(self):
        for name, kwargs in BYPASS_CASES:
            with self.subTest(rule=name):
                await self.assert_bypassed(self.bypass_call(), dict(kwargs))

    async def test_other_agent_types_are_never_cached(self):
        for agent_type in AGENT_TYPE_CASES:
            with self.subTest(agent_type=agent_type):
                call = self.bypass_call(task_manager=FakeTaskManager(agent_type))
                await self.assert_bypassed(call, dict(messages=user_turn(QUESTION), meta_info=meta()))

    async def test_controls_a_plain_caller_turn_is_still_served(self):
        controls = [
            ("the transcriber origin", {}, FakeTaskManager("simple_llm_agent")),
            ("no agent type at all", {}, FakeTaskManager(None)),
            ("no meta_info at all", {"meta_info": None}, FakeTaskManager()),
            ("no task manager at all", {}, None),
            ("a falsy parent_response_uid", {"meta_info": meta(parent_response_uid=None, eager_eot=False)},
             FakeTaskManager()),
        ]
        for name, kwargs, task_manager in controls:
            with self.subTest(case=name):
                call = Call(SceneStore({QUESTION: ANSWER}), task_manager=task_manager)
                chunks = await call.stream(user_turn(QUESTION), **kwargs)
                self.assertEqual(text_of(chunks), ANSWER)
                self.assertEqual(call.inner.calls, [])

    async def test_a_bypassed_turn_still_tells_the_session_what_the_caller_said(self):
        # A sentence that tells the call something (the core's "sets context" rule). The later
        # turn's messages leave it out, so only the bypassed turn's _heard() can taint the call.
        told = "I am vegetarian and I have a 3 year old daughter."
        store = SceneStore()
        call = Call(store)
        await call.stream(user_turn(told), meta_info=meta(eager_eot=True))  # bypassed, but heard
        call.tm.commit("r1", ANSWER)
        later = user_turn(QUESTION)
        await call.stream(later, meta_info=meta(2, "r2"))
        await call.end()
        self.assertEqual(call.inner.calls[-1]["messages"], later)  # the whole call, not the question alone
        self.assertEqual(store.writes, [])

    async def test_a_bypassed_tool_turn_is_not_a_caller_turn(self):
        call = self.bypass_call()
        await call.stream(_tool_messages(), meta_info=meta())
        self.assertEqual(call.session.stats()["turns"], 0)


# --- barge-in, tools, and what Bolna did with the answer -----------------------------------


class SettleTests(Base):
    async def saved_after(self, mutate):
        store = SceneStore()
        call = Call(store)
        chunks = await call.stream(user_turn(QUESTION), meta_info=meta(1, "r1"))
        mutate(call, text_of(chunks))
        await call.end()
        return store.writes

    async def test_a_complete_committed_reply_is_saved(self):
        writes = await self.saved_after(lambda call, text: call.tm.commit("r1", text))
        self.assertEqual(writes, [[QUESTION, ANSWER, False]])

    async def test_a_reply_trimmed_in_the_history_is_not_saved(self):
        writes = await self.saved_after(lambda call, text: call.tm.commit("r1", text[:14]))
        self.assertEqual(writes, [])

    async def test_a_reply_that_never_reached_the_history_is_not_saved(self):
        writes = await self.saved_after(lambda call, text: None)
        self.assertEqual(writes, [])

    async def test_a_row_for_another_response_is_not_this_reply(self):
        writes = await self.saved_after(lambda call, text: call.tm.commit("someone-else", text))
        self.assertEqual(writes, [])

    async def test_different_spacing_in_the_history_is_the_same_reply(self):
        writes = await self.saved_after(lambda call, text: call.tm.commit("r1", "  Refunds  take five\nbusiness days. "))
        self.assertEqual(writes, [[QUESTION, ANSWER, False]])

    async def test_a_reply_with_extra_words_in_the_history_is_not_saved(self):
        writes = await self.saved_after(lambda call, text: call.tm.commit("r1", text + " Anything else?"))
        self.assertEqual(writes, [])

    async def test_the_history_is_read_when_the_next_turn_starts(self):
        store = SceneStore()
        call = Call(store)
        await call.turn(QUESTION, committed=False)
        call.tm.commit("r1", ANSWER)  # the commit comes after the stream ended, before the next turn
        await call.turn("what are your opening hours", committed=False)
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    async def test_without_a_task_manager_the_answer_is_saved_once_settled(self):
        store = SceneStore()
        call = Call(store, task_manager=False)
        await call.turn(QUESTION)
        self.assertEqual(store.writes, [])
        await call.end()
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    async def test_without_a_task_manager_the_next_turn_settles_it(self):
        store = SceneStore()
        call = Call(store, task_manager=False)
        await call.turn(QUESTION)
        await call.turn("what are your opening hours")
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    async def test_closing_twice_saves_once(self):
        store = SceneStore()
        call = Call(store)
        await call.turn(QUESTION)
        await call.end()
        await call.end()
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    async def test_a_function_call_turn_is_never_saved(self):
        store = SceneStore()
        call = Call(store, reply="One moment while I check.", function_call=True)
        chunks = await call.stream(user_turn("what is the weather in paris today"))
        self.assertTrue(any(chunk.is_function_call for chunk in chunks))
        self.assertEqual(chunks, call.inner.scripted)
        call.tm.commit("r1", "One moment while I check.")
        await call.end()
        self.assertEqual(store.writes, [])

    async def test_an_inner_llm_that_fails_mid_answer_saves_nothing(self):
        store = SceneStore()
        call = Call(store, fail_after_first=True)
        with self.assertRaises(RuntimeError):
            await call.stream(user_turn(QUESTION))
        call.tm.commit("r1", ANSWER)
        await call.end()
        self.assertEqual(store.writes, [])


class CancelTests(Base):
    async def assert_nothing_kept(self, cancel):
        store = SceneStore()
        call = Call(store, reply="Refunds take five business days to reach your card.", gate=True)
        await cancel(call)
        call.tm.commit("r1", "Refunds take five business days to reach your card.")
        await call.end()
        self.assertEqual(store.writes, [])
        self.assertEqual(call.session.stats()["barge_ins"], 1)
        other = Call(store)
        await other.turn(QUESTION)
        self.assertEqual(len(other.inner.calls), 1)  # still a miss for another call

    async def test_closing_the_stream_early_saves_nothing(self):
        async def cancel(call):
            stream = call.llm.generate_stream(user_turn(QUESTION), meta_info=meta())
            await stream.__anext__()
            await stream.aclose()

        await self.assert_nothing_kept(cancel)

    async def test_a_cancelled_task_saves_nothing(self):
        async def cancel(call):
            async def consume():
                async for _ in call.llm.generate_stream(user_turn(QUESTION), meta_info=meta()):
                    pass

            task = asyncio.create_task(consume())
            await call.inner.paused.wait()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await self.assert_nothing_kept(cancel)

    async def test_the_next_turn_after_a_barge_in_is_saved_normally(self):
        store = SceneStore()
        call = Call(store, gate=True)
        stream = call.llm.generate_stream(user_turn(QUESTION), meta_info=meta())
        await stream.__anext__()
        await stream.aclose()
        call.inner.gate.set()
        await call.turn("what are your opening hours")
        await call.end()
        self.assertEqual(store.writes, [["what are your opening hours", ANSWER, False]])


# --- review findings B1-B3 ------------------------------------------------------------------


def log_inner_events(inner):
    """Record, in order, each chain reset and each generate_stream call of a FakeInner."""
    events = []
    reset, generate = inner.invalidate_response_chain, inner.generate_stream

    def logged_reset():
        events.append("reset")
        reset()

    def logged_generate(*args, **kwargs):
        events.append("call")
        return generate(*args, **kwargs)

    inner.invalidate_response_chain, inner.generate_stream = logged_reset, logged_generate
    return events


class ResponseChainTests(Base):
    async def test_b1_a_personal_turn_after_a_narrowed_call_resets_the_chain_first(self):
        call = Call(SceneStore(), reply=PERSONAL_ANSWER)
        events = log_inner_events(call.inner)
        await call.turn(QUESTION)  # a miss: the model reads the question alone
        await call.turn(PERSONAL)  # reads the whole call
        self.assertEqual(events, ["reset", "call", "reset", "call"])

    async def test_b1_a_bypassed_call_after_a_served_answer_resets_the_chain_first(self):
        call = Call(SceneStore({QUESTION: ANSWER}))
        events = log_inner_events(call.inner)
        await call.turn(QUESTION)  # served from the cache
        await call.stream(_tool_messages(), meta_info=meta(2, "r2"))  # a tool follow-up, bypassed
        self.assertEqual(events, ["reset", "reset", "call"])

    async def test_b1_the_chain_is_reset_once_not_on_every_full_context_call(self):
        call = Call(SceneStore(), reply=PERSONAL_ANSWER)
        events = log_inner_events(call.inner)
        await call.turn(QUESTION)
        await call.turn(PERSONAL)
        await call.turn("my order number is 48213, is it still on the way?")
        self.assertEqual(events, ["reset", "call", "reset", "call", "call"])

    async def test_b1_control_two_full_context_turns_never_reset_the_chain(self):
        call = Call(SceneStore(), reply=PERSONAL_ANSWER)
        await call.turn(PERSONAL)
        await call.turn("my order number is 48213, is it still on the way?")
        self.assertEqual(call.inner.chain_resets, 0)


class FunctionCallCloseTests(Base):
    async def test_b2_closing_the_stream_after_a_function_call_leaves_a_later_turn_alone(self):
        store = SceneStore()
        call = Call(store, reply="One moment while I check.", function_call=True)
        first = call.llm.generate_stream(user_turn("what is the weather in paris today"), meta_info=meta(1, "r1"))
        async for chunk in first:
            if chunk.is_function_call:
                break  # Bolna's consumer returns here and never reads the stream to its end
        call.inner.function_call = False
        await call.turn("what are your opening hours")  # decided and streamed before the late close
        await first.aclose()
        await call.end()
        self.assertEqual(store.writes, [["what are your opening hours", "One moment while I check.", False]])
        self.assertEqual(call.session.stats()["barge_ins"], 0)

    async def test_b2_control_a_real_mid_answer_cancel_still_cancels(self):
        call = Call(SceneStore(), reply="Refunds take five business days to reach your card.", gate=True)
        stream = call.llm.generate_stream(user_turn(QUESTION), meta_info=meta())
        await stream.__anext__()
        await stream.aclose()
        self.assertEqual(call.session.stats()["barge_ins"], 1)


class RegisteredWithoutCallContextTests(Base):
    def setUp(self):
        super().setUp()
        self._providers_before = dict(bolna_providers.SUPPORTED_LLM_PROVIDERS)
        
        class FakeBase(FakeInner):
            def __init__(inner_self, **kwargs):
                super().__init__(reply=ANSWER)

        bolna_providers.SUPPORTED_LLM_PROVIDERS[FAKE_BASE] = FakeBase

    def tearDown(self):
        bolna_providers.SUPPORTED_LLM_PROVIDERS.clear()
        bolna_providers.SUPPORTED_LLM_PROVIDERS.update(self._providers_before)

    def registered(self, store, **kwargs):
        cls = register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: make_session(store))
        return cls(language="en", model="m", provider="crowkis", **kwargs)

    async def test_b3_a_wrapper_built_without_a_task_manager_never_caches(self):
        store = SceneStore({QUESTION: "Never served."})
        llm = self.registered(store)
        messages = user_turn(QUESTION)
        chunks = [c async for c in llm.generate_stream(messages, meta_info=meta())]
        await llm.close()
        self.assertEqual(llm._inner.calls[0]["messages"], messages)  # to the model untouched
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(store.writes, [])

    async def test_b3_control_with_a_task_manager_it_still_caches(self):
        store = SceneStore()
        task_manager = FakeTaskManager()
        llm = self.registered(store, task_manager_instance=task_manager)
        chunks = [c async for c in llm.generate_stream(user_turn(QUESTION), meta_info=meta())]
        task_manager.commit("r1", text_of(chunks))
        await llm.close()
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])


# --- the system prompt's caller details -----------------------------------------------------


class PromptGuardTests(Base):
    async def test_an_answer_repeating_a_caller_detail_from_the_system_prompt_is_not_shared(self):
        store = SceneStore()
        call = Call(store, reply="Hi Priya! We open at nine.")
        system = "You are Acme's phone assistant.\nCaller name: Priya Sharma, phone 98450 12345"
        await call.turn("what are your opening hours", system=system)
        await call.end()
        self.assertEqual(store.writes, [])
        other = Call(store)
        await other.turn("what are your opening hours", system=system)
        self.assertEqual(len(other.inner.calls), 1)

    async def test_the_shared_prompt_fixture_is_guarded_too(self):
        store = SceneStore()
        call = Call(store, reply="Hi Asha! We open at nine.")
        await call.turn("what are your opening hours", system=PROMPT)
        await call.end()
        self.assertEqual(store.writes, [])

    async def test_control_a_generic_answer_with_the_same_prompt_is_shared(self):
        store = SceneStore()
        system = "You are Acme's phone assistant.\nCaller name: Priya Sharma, phone 98450 12345"
        call = Call(store, reply="We open at nine every morning.")
        await call.turn("what are your opening hours", system=system)
        await call.end()
        self.assertEqual(store.writes, [["what are your opening hours", "We open at nine every morning.", False]])
        other = Call(store, reply="never asked")
        chunks = await other.turn("what are your opening hours", system=system)
        self.assertEqual(text_of(chunks), "We open at nine every morning.")
        self.assertEqual(other.inner.calls, [])


# --- failures in Crowkis --------------------------------------------------------------------


class FailOpenTests(Base):
    async def test_a_session_that_cannot_decide_leaves_the_turn_to_the_inner_llm(self):
        store = SceneStore({QUESTION: "Never reached."})
        call = Call(store, session=BoundSession(make_session(store), decide=True))
        messages = user_turn(QUESTION)
        chunks = await call.stream(messages)
        self.assertEqual(call.inner.calls[0]["messages"], messages)
        self.assertEqual(chunks, call.inner.scripted)
        call.tm.commit("r1", ANSWER)
        await call.end()
        again = await call.stream(user_turn("and another question"), meta_info=meta(2, "r2"))
        self.assertEqual(text_of(again), ANSWER)  # the call goes on

    async def test_a_session_that_cannot_record_never_breaks_the_call(self):
        store = SceneStore()
        call = Call(store, session=BoundSession(make_session(store), record=True))
        await call.turn(QUESTION)
        await call.end()  # the failed save is swallowed at the boundary
        again = await call.turn("what are your opening hours")
        await call.end()
        self.assertEqual(text_of(again), ANSWER)
        self.assertEqual(store.writes, [])

    async def test_a_cache_that_is_down_is_counted_and_the_model_answers(self):
        class DownStore(SceneStore):
            def cget_hit(self, query, **kwargs):
                raise ConnectionError("cache down")

        store = DownStore()
        call = Call(store)
        chunks = await call.turn(QUESTION)
        await call.end()
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertGreaterEqual(call.session.stats()["cache_unavailable"], 1)


# --- calls never see each other -------------------------------------------------------------


class ConcurrencyTests(Base):
    async def test_two_calls_at_once_never_see_each_others_personal_answers(self):
        store = SceneStore()
        first = Call(store, reply="Order 48213 left the depot this morning.")
        second = Call(store, reply="Order 77120 is out for delivery today.")
        chunks_one, chunks_two = await asyncio.gather(
            first.turn("my order 48213 has not arrived where is it"),
            second.turn("my order 77120 has not arrived where is it"),
        )
        await asyncio.gather(first.end(), second.end())
        self.assertEqual(text_of(chunks_one), "Order 48213 left the depot this morning.")
        self.assertEqual(text_of(chunks_two), "Order 77120 is out for delivery today.")
        self.assertEqual(store.writes, [])
        third = Call(store, reply="Please give me your order number.")
        for text in ("my order 48213 has not arrived where is it", "my order 77120 has not arrived where is it"):
            await third.turn(text, committed=False)
        self.assertEqual(len(third.inner.calls), 2)

    async def test_control_concurrent_shared_questions_are_shared(self):
        store = SceneStore()
        first = Call(store)
        second = Call(store, reply="Open settings, then security.")
        await asyncio.gather(first.turn(QUESTION), second.turn("how do I reset my password"))
        await asyncio.gather(first.end(), second.end())
        self.assertEqual(sorted(store.shared), sorted([QUESTION, "how do I reset my password"]))
        third = Call(store, reply="never")
        chunks = await third.turn("how do I reset my password")
        self.assertEqual(text_of(chunks), "Open settings, then security.")

    async def test_a_personal_and_a_shared_turn_at_once_do_not_cross(self):
        store = SceneStore()
        personal = Call(store, reply=PERSONAL_ANSWER)
        general = Call(store)
        await asyncio.gather(personal.turn(PERSONAL), general.turn(QUESTION))
        await asyncio.gather(personal.end(), general.end())
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])
        self.assertNotIn("48213", repr(store.shared))


# --- odd texts ------------------------------------------------------------------------------


class EdgeTextTests(Base):
    async def test_an_empty_caller_turn_goes_on_and_is_not_shared(self):
        store = SceneStore()
        call = Call(store, reply="Sorry, I did not catch that.")
        chunks = await call.turn("")
        await call.end()
        self.assertEqual(text_of(chunks), "Sorry, I did not catch that.")
        self.assertEqual(store.writes, [])

    async def test_a_very_long_turn_streams_the_answer(self):
        store = SceneStore()
        call = Call(store)
        long_text = (QUESTION + " ") * 200
        self.assertGreater(len(long_text), 5000)
        chunks = await call.turn(long_text)
        await call.end()
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(call.inner.calls[0]["messages"][-1]["content"], long_text)
        self.assertNotIn(long_text, repr(store.shared))  # an essay is not a cache key

    async def test_devanagari_text_streams_and_is_never_leaked_across_calls(self):
        question = "आपकी रिफंड पॉलिसी क्या है"
        answer = "रिफंड पाँच दिन में आपके कार्ड तक पहुँच जाता है।"
        store = SceneStore()
        call = Call(store, reply=answer)
        chunks = await call.turn(question)
        await call.end()
        self.assertEqual(text_of(chunks), answer)
        self.assertEqual(call.inner.calls[0]["messages"][-1]["content"], question)

    async def test_a_served_devanagari_answer_is_chunked_on_spaces(self):
        question = "refund kitne din mein milta hai"
        answer = "रिफंड पाँच दिन में आपके कार्ड तक पहुँच जाता है और हम एक ईमेल भी भेजते हैं।"
        call = Call(SceneStore({question: answer}))
        chunks = await call.stream(user_turn(question))
        self.assertEqual(" ".join(chunk.data.strip() for chunk in chunks), answer)
        self.assertEqual(call.inner.calls, [])
        self.assertTrue(chunks[-1].end_of_stream)

    async def test_a_hinglish_personal_question_stays_in_the_call(self):
        store = SceneStore()
        call = Call(store, reply="Aapka order kal tak aa jayega.")
        await call.turn("mera order kab aayega")
        await call.end()
        self.assertEqual(store.writes, [])
        other = Call(store, reply="Order number batayiye.")
        await other.turn("mera order kab aayega")
        self.assertEqual(len(other.inner.calls), 1)

    async def test_a_general_hinglish_question_is_shared(self):
        store = SceneStore()
        call = Call(store, reply="Paanch din mein.")
        await call.turn("refund kitne din mein milta hai")
        await call.end()
        self.assertEqual(store.writes, [["refund kitne din mein milta hai", "Paanch din mein.", False]])

    async def test_numbers_with_separators_are_personal(self):
        store = SceneStore()
        call = Call(store, reply="We will call 98450 12345 back.")
        await call.turn("my phone is 98450 12345 call me back")
        await call.end()
        self.assertEqual(store.writes, [])
        self.assertEqual(store.tool_writes, [])



# --- audio: cached voice clips --------------------------------------------------------------
#
# Bolna builds one synthesizer per call, next to its LLM, and the two never meet. The wrappers
# meet through a CallLinks object that register_crowkis() hands to both; it is keyed by the
# call's task manager. The synthesizer is faked here as a BaseSynthesizer whose generate()
# yields one packet per pushed text, with the meta Bolna's own synthesizers stamp.


FAKE_SYNTH = "crowkis-test-fake-synth"
CLIP = b"\x01\x02\x03\x04-a-clip-made-earlier"
OTHER_ANSWER = "We open at nine every morning."


def audio_for(text):
    """What the fake synthesizer 'says' for a text: the text itself, as bytes."""
    return b"\x00" if not text or not text.strip() else f"<{text}>".encode()


def audio_of(texts):
    return b"".join(audio_for(text) for text in texts if text and text.strip())


def pieces_of(chunks):
    return [chunk.data for chunk in chunks if chunk.data]


class FakeSynth(BaseSynthesizer):
    """A Bolna synthesizer: push() queues text, generate() yields a packet for each."""

    def __init__(self, *, task_manager_instance=None, voice="nova", wire_format="mulaw", sample_rate=8000,
                 stream=False, **kwargs):
        super().__init__(task_manager_instance, stream=stream, buffer_size=BUFFER)
        self.voice = voice
        self.sample_rate = sample_rate
        self.wire_format = wire_format
        self.model = "fake-tts"
        self.pushed = []
        self.calls = Counter()
        self.kwargs = kwargs

    def _get_audio_format(self):
        return self.wire_format

    def _get_http_audio_format(self):
        return self.wire_format

    async def push(self, message):
        self.pushed.append(copy.deepcopy(message))
        await super().push(message)

    async def generate(self):
        while True:
            message = await self.internal_queue.get()
            meta_info, text = message["meta_info"], message["data"]
            self._stamp_first_chunk(meta_info)
            self._stamp_end_of_stream(meta_info)
            meta_info["format"] = self.wire_format
            meta_info["text"] = text
            meta_info["text_synthesized"] = f"{text} "
            self._stamp_mark_id(meta_info)
            yield create_ws_data_packet(audio_for(text), meta_info)

    async def handle_interruption(self):
        self.calls["handle_interruption"] += 1  # the queue is left alone: late audio can still arrive

    async def flush_synthesizer_stream(self):
        self.calls["flush_synthesizer_stream"] += 1

    async def cleanup(self):
        self.calls["cleanup"] += 1

    async def monitor_connection(self):
        self.calls["monitor_connection"] += 1

    async def synthesize(self, text):
        self.calls["synthesize"] += 1
        return audio_for(text)

    def clear_internal_queue(self):
        self.calls["clear_internal_queue"] += 1

    def get_engine(self):
        self.calls["get_engine"] += 1
        return self.model


class ToolFailingStore(SceneStore):
    """A cache whose audio reads and writes both raise."""

    def ctoolget(self, tool, key, *, tenant=None):
        raise RuntimeError("audio read exploded")

    def ctoolset(self, tool, key, value, *, ex=None, tenant=None):
        raise RuntimeError("audio write exploded")


class UnshareableAudio:
    """A session whose served answers are filled with this caller's values."""

    def __init__(self, real):
        self._real = real

    async def decide(self, caller_said):
        decision = await self._real.decide(caller_said)
        decision._audio_shareable = False
        return decision

    def __getattr__(self, name):
        return getattr(self._real, name)


class AudioCall(Call):
    """A call with its synthesizer next to its LLM, linked the way register_crowkis() links them."""

    def __init__(self, store, links, reply=ANSWER, *, voice="nova", wire_format="mulaw", sample_rate=8000,
                 **options):
        super().__init__(store, reply, **options)
        self.voice = voice
        self.wire_format = wire_format
        self.sample_rate = sample_rate
        self.synth_inner = FakeSynth(task_manager_instance=self.tm, voice=voice, wire_format=wire_format,
                                     sample_rate=sample_rate)
        self.llm = CrowkisLLM(self.inner, self.session, task_manager=self.tm, links=links)
        self.synth = CrowkisSynthesizer(self.synth_inner, links)

    @property
    def key_format(self):
        return "mulaw-8000" if self.wire_format == "mulaw" else f"pcm16-{self.sample_rate}"

    def clip_key(self, text, key_format=None):
        session = self.session
        return _tts_key(text, (self.voice, session.language, str(session.speed), key_format or self.key_format))

    def hear_clip(self, text, clip=CLIP):
        """The server already holds a clip for this answer, in this call's voice and format."""
        self.store.tool[self.clip_key(text)] = base64.b64encode(clip).decode("ascii")

    def stored_clips(self):
        """[text, format, audio] of every clip written to the cache's audio store."""
        _wait_for_audio_stores()
        return [[write[0]["text"], write[0]["format"], base64.b64decode(write[1])]
                for write in self.store.tool_writes]

    async def say(self, text, *, committed=True, system=SYSTEM):
        """A caller turn, then the speech of its answer, as Bolna's task manager drives them."""
        chunks = await self.turn(text, committed=False, system=system)
        packets = await self.speak(chunks)
        if committed:
            self.tm.commit(f"r{self.sequence}", text_of(chunks))
        return chunks, packets

    async def push(self, chunk):
        await self.push_text(chunk.data, chunk.end_of_stream)

    async def push_text(self, text, end_of_llm_stream):
        await self.synth.push({"data": text, "meta_info": {
            "sequence_id": self.sequence, "turn_id": self.sequence, "end_of_llm_stream": end_of_llm_stream}})

    async def speak(self, chunks):
        """Push every text piece of an answer to the synthesizer, then read its audio."""
        spoken = [chunk for chunk in chunks if not chunk.is_function_call]
        for chunk in spoken:
            await self.push(chunk)
        if not any(chunk.end_of_stream for chunk in spoken):
            await self.push_text("", True)  # the bare marker that closes a turn
        return await self.packets()

    async def packets(self, wanted=None):
        """Packets from generate(), up to the end of the synthesizer stream (or ``wanted`` packets)."""
        found = []
        stream = self.synth.generate()
        async with contextlib.aclosing(stream):
            async with asyncio.timeout(3):
                async for packet in stream:
                    found.append(packet)
                    if len(found) == wanted or packet["meta_info"].get("end_of_synthesizer_stream"):
                        break
        return found


class AudioBase(Base):
    def setUp(self):
        super().setUp()
        self.links = CallLinks()
        _wait_for_audio_stores()


class ServedClipTests(AudioBase):
    async def test_a_served_answer_whose_clip_is_cached_plays_the_clip(self):
        for wire_format, rate in (("mulaw", 8000), ("pcm", 24000)):
            with self.subTest(wire_format=wire_format):
                call = AudioCall(SceneStore({QUESTION: ANSWER}), self.links, wire_format=wire_format,
                                 sample_rate=rate)
                call.hear_clip(ANSWER)
                chunks, packets = await call.say(QUESTION)
                self.assertEqual(text_of(chunks), ANSWER)
                self.assertEqual(call.synth_inner.pushed, [])  # the inner synthesizer is never given the text
                self.assertEqual(len(packets), 1)
                self.assertEqual(packets[0]["data"], CLIP)
                self.assertEqual(call.stored_clips(), [])  # a clip heard from the cache is not stored again

    async def test_the_clip_packet_carries_the_meta_bolna_needs(self):
        call = AudioCall(SceneStore({QUESTION: LONG_ANSWER}), self.links)
        call.hear_clip(LONG_ANSWER)
        chunks, packets = await call.say(QUESTION)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(len(packets), 1)  # the whole answer is one clip, ended in the same packet
        meta = packets[0]["meta_info"]
        self.assertEqual(meta["format"], "mulaw")
        self.assertEqual(meta["text"], LONG_ANSWER)
        self.assertEqual(meta["text_synthesized"], LONG_ANSWER + " ")
        self.assertEqual((meta["sequence_id"], meta["turn_id"]), (1, 1))
        self.assertTrue(meta["is_first_chunk"])
        self.assertTrue(meta["end_of_llm_stream"])
        self.assertTrue(meta["end_of_synthesizer_stream"])
        self.assertTrue(meta["mark_id"])
        self.assertNotIn("cached", meta)  # Bolna reads cached=True as "play the welcome clip"

    async def test_the_next_answer_is_an_ordinary_first_chunk_again(self):
        call = AudioCall(SceneStore({QUESTION: ANSWER, "what are your hours": OTHER_ANSWER}), self.links)
        call.hear_clip(ANSWER)
        await call.say(QUESTION)
        _, packets = await call.say("what are your hours")  # a hit with no clip: the inner synthesizer speaks
        self.assertEqual(packets[0]["data"], audio_for(OTHER_ANSWER))
        self.assertTrue(packets[0]["meta_info"]["is_first_chunk"])

    async def test_control_a_served_answer_with_no_clip_is_spoken_by_the_inner_synth_and_then_stored(self):
        for wire_format, rate, key_format in (("mulaw", 8000, "mulaw-8000"), ("pcm", 24000, "pcm16-24000")):
            with self.subTest(key_format=key_format):
                call = AudioCall(SceneStore({QUESTION: LONG_ANSWER}), self.links, wire_format=wire_format,
                                 sample_rate=rate)
                chunks, packets = await call.say(QUESTION)
                self.assertEqual([m["data"] for m in call.synth_inner.pushed], pieces_of(chunks))
                self.assertEqual(b"".join(p["data"] for p in packets), audio_of(pieces_of(chunks)))
                self.assertEqual(call.stored_clips(), [[LONG_ANSWER, key_format, audio_of(pieces_of(chunks))]])
                self.assertEqual(call.store.writes, [])  # the text was already shared; only audio is new

    async def test_a_served_answer_that_is_not_audio_shareable_never_uses_the_shared_clip(self):
        store = SceneStore({QUESTION: ANSWER})
        call = AudioCall(store, self.links, session=UnshareableAudio(make_session(store)))
        call.hear_clip(ANSWER)
        chunks, packets = await call.say(QUESTION)
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual([m["data"] for m in call.synth_inner.pushed], [ANSWER])
        self.assertEqual(packets[0]["data"], audio_for(ANSWER))
        self.assertEqual(call.stored_clips(), [])  # nor is this caller's audio put in the shared cache

    async def test_a_clip_for_another_format_is_not_this_calls_clip(self):
        call = AudioCall(SceneStore({QUESTION: ANSWER}), self.links, wire_format="mulaw", sample_rate=8000)
        call.store.tool[call.clip_key(ANSWER, "pcm16-24000")] = base64.b64encode(CLIP).decode("ascii")
        _, packets = await call.say(QUESTION)
        self.assertEqual(packets[0]["data"], audio_for(ANSWER))

    async def test_a_clip_for_another_voice_is_not_this_calls_clip(self):
        store = SceneStore({QUESTION: ANSWER})
        AudioCall(store, self.links, voice="shimmer").hear_clip(ANSWER)
        call = AudioCall(store, self.links, voice="nova")
        _, packets = await call.say(QUESTION)
        self.assertEqual(packets[0]["data"], audio_for(ANSWER))

    async def test_a_damaged_clip_is_a_miss(self):
        call = AudioCall(SceneStore({QUESTION: ANSWER}), self.links)
        call.store.tool[call.clip_key(ANSWER)] = "not base64 !!"
        _, packets = await call.say(QUESTION)
        self.assertEqual(packets[0]["data"], audio_for(ANSWER))


class SavedAnswerAudioTests(AudioBase):
    async def test_an_answer_saved_word_for_word_has_its_audio_stored_for_its_format(self):
        for wire_format, rate, key_format in (("mulaw", 8000, "mulaw-8000"), ("pcm", 24000, "pcm16-24000")):
            with self.subTest(key_format=key_format):
                call = AudioCall(SceneStore(), self.links, LONG_ANSWER, wire_format=wire_format, sample_rate=rate)
                chunks, _ = await call.say(QUESTION)
                await call.end()
                self.assertEqual(call.store.writes, [[QUESTION, LONG_ANSWER, False]])
                self.assertEqual(call.stored_clips(), [[LONG_ANSWER, key_format, audio_of(pieces_of(chunks))]])
                self.assertEqual(call.store.tool_writes[0][0], json.loads(call.clip_key(LONG_ANSWER)))

    async def test_the_stored_clip_is_played_to_the_next_caller(self):
        store = SceneStore()
        first = AudioCall(store, self.links, LONG_ANSWER)
        chunks, _ = await first.say(QUESTION)
        await first.end()
        first.stored_clips()
        second = AudioCall(store, self.links, "never asked")
        heard, packets = await second.say(QUESTION)
        self.assertEqual(text_of(heard), LONG_ANSWER)
        self.assertEqual(second.synth_inner.pushed, [])
        self.assertEqual(packets[0]["data"], audio_of(pieces_of(chunks)))

    async def test_the_clip_waits_for_the_ruling_when_the_reply_is_committed_late(self):
        call = AudioCall(SceneStore(), self.links)
        await call.say(QUESTION, committed=False)
        self.assertEqual(call.stored_clips(), [])  # spoken, but not yet known to be saved
        call.tm.commit("r1", ANSWER)
        await call.end()
        self.assertEqual([clip[0] for clip in call.stored_clips()], [ANSWER])

    async def test_the_ruling_can_come_before_the_audio_ends(self):
        call = AudioCall(SceneStore(), self.links)
        chunks = await call.turn(QUESTION, committed=True)
        await call.end()  # settled: the answer is saved
        await call.speak(chunks)
        self.assertEqual([clip[0] for clip in call.stored_clips()], [ANSWER])

    async def test_a_reply_trimmed_by_a_barge_in_has_no_clip(self):
        call = AudioCall(SceneStore(), self.links, LONG_ANSWER)
        await call.say(QUESTION, committed=False)
        call.tm.commit("r1", "Refunds take five business days")  # what was spoken before the caller cut in
        await call.end()
        self.assertEqual(call.store.writes, [])
        self.assertEqual(call.stored_clips(), [])

    async def test_a_private_answer_has_no_clip(self):
        system = "You are Acme's phone assistant.\nCaller name: Priya Sharma, phone 98450 12345"
        call = AudioCall(SceneStore(), self.links, "Hi Priya! We open at nine.")
        await call.say("what are your opening hours", system=system)
        await call.end()
        self.assertEqual(call.store.writes, [])
        self.assertEqual(call.stored_clips(), [])

    async def test_a_personal_turn_has_no_clip(self):
        call = AudioCall(SceneStore(), self.links, PERSONAL_ANSWER)
        await call.say(PERSONAL)
        await call.end()
        self.assertEqual(call.stored_clips(), [])

    async def test_a_function_call_turn_has_no_clip(self):
        call = AudioCall(SceneStore(), self.links, "Let me check the weather", function_call=True)
        await call.say(QUESTION)
        await call.end()
        self.assertEqual(call.store.writes, [])
        self.assertEqual(call.stored_clips(), [])

    async def test_a_template_has_no_clip(self):
        store = SceneStore()
        session = AsyncVoiceSession.wrap(VoiceSession(Agent("caller", client=store), voice="v",
                                                      values={"order_id": "ORD-111"}, share_templates=True))
        call = AudioCall(store, self.links, "Your order ORD-111 arrives on Tuesday.", session=session)
        await call.say("when will my order arrive")
        await call.end()
        self.assertEqual(store.writes,
                         [["when will my order arrive", "Your order {order_id} arrives on Tuesday.", True]])
        self.assertEqual(call.stored_clips(), [])  # the audio still says this caller's value

    async def test_an_answer_the_server_holds_has_no_clip_until_it_is_served(self):
        call = AudioCall(SceneStore(), self.links)
        call.session.agent.decides = lambda: True  # the server's decision engine holds new answers
        call.session.agent._holds = True
        await call.say(QUESTION)
        await call.end()
        self.assertEqual(call.stored_clips(), [])

    async def test_a_sequence_that_never_finished_has_no_clip(self):
        call = AudioCall(SceneStore(), self.links, LONG_ANSWER)
        chunks = await call.turn(QUESTION, committed=True)
        await call.push(chunks[0])  # the rest of the text never reached the synthesizer
        await call.packets(wanted=1)
        await call.end()
        self.assertEqual(call.stored_clips(), [])

    async def test_audio_in_another_format_than_the_synth_declared_is_not_stored(self):
        call = AudioCall(SceneStore(), self.links)
        chunks = await call.turn(QUESTION, committed=True)
        call.synth_inner.wire_format = "wav"  # what the packets say they carry, not what was declared
        await call.speak(chunks)
        await call.end()
        self.assertEqual(call.stored_clips(), [])

    async def test_audio_of_other_words_is_not_stored_under_the_answer(self):
        call = AudioCall(SceneStore(), self.links)
        await call.turn(QUESTION, committed=True)
        await call.speak([LLMStreamChunk(data="Something else entirely.", end_of_stream=True)])
        await call.end()
        self.assertEqual(call.stored_clips(), [])


class InterruptionAudioTests(AudioBase):
    async def test_handle_interruption_mid_clip_drops_the_collected_audio(self):
        call = AudioCall(SceneStore(), self.links, LONG_ANSWER)
        chunks = await call.turn(QUESTION, committed=True)
        for chunk in chunks:
            await call.push(chunk)
        await call.packets(wanted=1)  # the first piece is out
        await call.synth.handle_interruption()
        await call.packets()  # late audio of the cut-off answer still comes out of the provider
        await call.end()  # and Bolna's history says the answer was complete
        self.assertEqual(call.store.writes, [[QUESTION, LONG_ANSWER, False]])
        self.assertEqual(call.stored_clips(), [])
        self.assertEqual(call.synth_inner.calls["handle_interruption"], 1)

    async def test_handle_interruption_drops_an_order_to_play_a_clip(self):
        call = AudioCall(SceneStore({QUESTION: LONG_ANSWER}), self.links)
        call.hear_clip(LONG_ANSWER)
        chunks = await call.turn(QUESTION, committed=False)
        await call.synth.handle_interruption()
        await call.push(chunks[0])  # leftovers of the old answer arrive after the caller cut in
        self.assertEqual([m["data"] for m in call.synth_inner.pushed], [chunks[0].data])  # no longer swallowed

    async def test_cancelling_the_response_drops_the_audio_too(self):
        call = AudioCall(SceneStore(), self.links)
        chunks = await call.turn(QUESTION, committed=False)
        await call.speak(chunks)
        call.llm.cancel_in_flight_response()
        call.tm.commit("r1", ANSWER)
        await call.end()
        self.assertEqual(call.stored_clips(), [])


class CallLinkTests(AudioBase):
    async def test_two_calls_never_mix_clips(self):
        store = SceneStore({QUESTION: ANSWER})
        first = AudioCall(store, self.links)
        first.hear_clip(ANSWER)
        second = AudioCall(store, self.links, OTHER_ANSWER)
        first_chunks = await first.turn(QUESTION, committed=False)  # sequence 1 of the first call
        second_chunks = await second.turn("what are your opening hours", committed=False)  # sequence 1 too
        second_packets = await second.speak(second_chunks)
        first_packets = await first.speak(first_chunks)
        self.assertEqual(first_packets[0]["data"], CLIP)
        self.assertEqual(first.synth_inner.pushed, [])
        self.assertEqual([m["data"] for m in second.synth_inner.pushed], pieces_of(second_chunks))
        self.assertEqual(b"".join(p["data"] for p in second_packets), audio_of(pieces_of(second_chunks)))
        first.tm.commit("r1", text_of(first_chunks))
        second.tm.commit("r1", text_of(second_chunks))
        await first.end()
        await second.end()
        self.assertEqual(second.stored_clips(),
                         [[OTHER_ANSWER, "mulaw-8000", audio_of(pieces_of(second_chunks))]])

    async def test_the_link_between_a_calls_llm_and_synth_is_the_calls_task_manager(self):
        call = AudioCall(SceneStore(), self.links)
        other = AudioCall(SceneStore(), self.links)
        self.assertIs(self.links.plan_for(call.tm), self.links.plan_for(call.tm))
        self.assertIsNot(self.links.plan_for(call.tm), self.links.plan_for(other.tm))

    async def test_a_call_with_two_synthesizers_keeps_no_clips(self):
        # Bolna's multilingual pool builds one synthesizer per language for the same call, each
        # with its own voice: one shared plan can't know which voice a clip is in.
        call = AudioCall(SceneStore({QUESTION: ANSWER}), self.links)
        call.hear_clip(ANSWER)
        CrowkisSynthesizer(FakeSynth(task_manager_instance=call.tm, voice="shimmer"), self.links)
        plan = self.links.plan_for(call.tm)
        self.assertIsNone(plan.wire_format)
        self.assertIsNone(await plan.fetch(ANSWER))

    async def test_a_call_that_ended_leaves_nothing_behind(self):
        links = CallLinks()
        task_manager = FakeTaskManager()
        reference = weakref.ref(task_manager)
        links.plan_for(task_manager)
        del task_manager
        gc.collect()
        self.assertIsNone(reference())

    async def test_a_synth_with_no_task_manager_passes_everything_through(self):
        inner = FakeSynth(task_manager_instance=None)
        synth = CrowkisSynthesizer(inner, self.links)
        await synth.push({"data": "hello there", "meta_info": {"sequence_id": 1, "end_of_llm_stream": True}})
        self.assertEqual([m["data"] for m in inner.pushed], ["hello there"])


class AudioFailOpenTests(AudioBase):
    async def test_a_cache_that_cannot_read_or_write_audio_lets_the_inner_synth_speak(self):
        call = AudioCall(ToolFailingStore({QUESTION: ANSWER}), self.links)
        chunks, packets = await call.say(QUESTION)
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(packets[0]["data"], audio_for(ANSWER))
        self.assertEqual([m["data"] for m in call.synth_inner.pushed], [ANSWER])
        _wait_for_audio_stores()

    async def test_a_model_answer_still_speaks_when_its_clip_cannot_be_written(self):
        call = AudioCall(ToolFailingStore(), self.links)
        chunks, packets = await call.say(QUESTION)
        await call.end()
        self.assertEqual(b"".join(p["data"] for p in packets), audio_of(pieces_of(chunks)))
        _wait_for_audio_stores()

    async def test_a_clip_store_that_raises_is_counted_and_never_reaches_the_call(self):
        class Exploding:
            async def get(self, text):
                raise RuntimeError("shelf exploded")

            async def store_clip(self, text, clip):
                raise RuntimeError("shelf exploded")

        served = AudioCall(SceneStore({QUESTION: ANSWER}), self.links)
        self.links.plan_for(served.tm)._shelf = Exploding()
        _, packets = await served.say(QUESTION)
        self.assertEqual(packets[0]["data"], audio_for(ANSWER))
        self.assertEqual([m["data"] for m in served.synth_inner.pushed], [ANSWER])
        asked = AudioCall(SceneStore(), self.links)
        self.links.plan_for(asked.tm)._shelf = Exploding()
        chunks, packets = await asked.say(QUESTION)
        await asked.end()
        self.assertEqual(b"".join(p["data"] for p in packets), audio_of(pieces_of(chunks)))
        self.assertGreaterEqual(served.llm.failures["audio"], 1)
        self.assertEqual(asked.llm.failures["audio"], 1)


class SynthDelegationTests(AudioBase):
    async def test_every_other_method_reaches_the_inner_synth(self):
        call = AudioCall(SceneStore(), self.links)
        synth, inner = call.synth, call.synth_inner
        await synth.flush_synthesizer_stream()
        await synth.cleanup()
        await synth.monitor_connection()
        self.assertEqual(await synth.synthesize("hi"), audio_for("hi"))
        synth.clear_internal_queue()
        self.assertEqual(synth.get_engine(), "fake-tts")
        await synth.handle_interruption()
        for name in ("flush_synthesizer_stream", "cleanup", "monitor_connection", "synthesize",
                     "clear_internal_queue", "get_engine", "handle_interruption"):
            self.assertEqual(inner.calls[name], 1, name)
        self.assertEqual(synth.model, "fake-tts")
        self.assertEqual(synth.buffer_size, BUFFER)
        self.assertEqual(synth.get_sleep_time(), 0.2)
        self.assertTrue(synth.supports_websocket())

    async def test_a_sequence_with_no_order_is_pushed_untouched(self):
        call = AudioCall(SceneStore(), self.links)
        message = {"data": "Hello, welcome.", "meta_info": {"sequence_id": -1, "end_of_llm_stream": True,
                                                            "message_category": "agent_welcome_message"}}
        await call.synth.push(copy.deepcopy(message))
        self.assertEqual(call.synth_inner.pushed, [message])
        packets = await call.packets()
        self.assertEqual(packets[0]["data"], audio_for("Hello, welcome."))

    async def test_a_synth_that_fails_in_generate_fails_the_same_way(self):
        call = AudioCall(SceneStore(), self.links)

        async def broken():
            raise ConnectionError("tts socket closed")
            yield

        call.synth_inner.generate = broken
        with self.assertRaises(ConnectionError):
            async for _ in call.synth.generate():
                pass

    async def test_generate_ends_when_the_inner_generate_ends(self):
        call = AudioCall(SceneStore(), self.links)

        async def finished():
            return
            yield

        call.synth_inner.generate = finished
        async with asyncio.timeout(3):
            self.assertEqual([packet async for packet in call.synth.generate()], [])


class RegisterSynthesizerTests(unittest.TestCase):
    def setUp(self):
        self._llms_before = dict(bolna_providers.SUPPORTED_LLM_PROVIDERS)
        self._synths_before = dict(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS)
        bolna_providers.SUPPORTED_LLM_PROVIDERS[FAKE_BASE] = FakeInner
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[FAKE_SYNTH] = FakeSynth
        self._synths_with_fake = dict(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS)

    def tearDown(self):
        bolna_providers.SUPPORTED_LLM_PROVIDERS.clear()
        bolna_providers.SUPPORTED_LLM_PROVIDERS.update(self._llms_before)
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.clear()
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.update(self._synths_before)

    def register(self, **options):
        return register_crowkis(name="crowkis-test", base=FAKE_BASE, session_factory=lambda: None, **options)

    def test_without_a_synthesizer_the_audio_registry_is_untouched(self):
        self.register()
        self.assertEqual(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS, self._synths_with_fake)

    def test_the_named_synthesizer_is_wrapped_and_the_others_are_not(self):
        self.register(synthesizer=FAKE_SYNTH)
        registry = bolna_providers.SUPPORTED_SYNTHESIZER_MODELS
        self.assertTrue(issubclass(registry[FAKE_SYNTH], CrowkisSynthesizer))
        for name, cls in self._synths_with_fake.items():
            if name != FAKE_SYNTH:
                self.assertIs(registry[name], cls)

    def test_the_wrapper_builds_as_bolna_builds_a_synthesizer(self):
        self.register(synthesizer=FAKE_SYNTH)
        synth = bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[FAKE_SYNTH](
            voice="alloy", sampling_rate=24000, caching=True, task_manager_instance=FakeTaskManager())
        self.assertIsInstance(synth._inner, FakeSynth)
        self.assertEqual(synth.voice, "alloy")
        self.assertEqual(synth._inner.kwargs, {"sampling_rate": 24000, "caching": True})

    def test_registering_twice_wraps_the_original_once(self):
        self.register(synthesizer=FAKE_SYNTH)
        self.register(synthesizer=FAKE_SYNTH)
        synth = bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[FAKE_SYNTH](voice="alloy")
        self.assertIs(type(synth._inner), FakeSynth)

    def test_an_unknown_synthesizer_is_refused(self):
        with self.assertRaises(CrowkisBolnaError):
            self.register(synthesizer="no-such-synth")
        self.assertEqual(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS, self._synths_with_fake)
        self.assertNotIn("crowkis-test", bolna_providers.SUPPORTED_LLM_PROVIDERS)

    def test_bolnas_task_manager_sees_the_wrapped_synthesizer(self):
        from bolna.agent_manager import task_manager as tm

        self.register(synthesizer=FAKE_SYNTH)
        self.assertIs(tm.SUPPORTED_SYNTHESIZER_MODELS, bolna_providers.SUPPORTED_SYNTHESIZER_MODELS)
        self.assertIsNot(tm.SUPPORTED_SYNTHESIZER_MODELS[FAKE_SYNTH], FakeSynth)


class RegisteredPairTests(Base):
    def setUp(self):
        super().setUp()
        self._llms_before = dict(bolna_providers.SUPPORTED_LLM_PROVIDERS)
        self._synths_before = dict(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS)
        bolna_providers.SUPPORTED_LLM_PROVIDERS[FAKE_BASE] = FakeInner
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[FAKE_SYNTH] = FakeSynth

    def tearDown(self):
        bolna_providers.SUPPORTED_LLM_PROVIDERS.clear()
        bolna_providers.SUPPORTED_LLM_PROVIDERS.update(self._llms_before)
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.clear()
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.update(self._synths_before)

    async def test_the_registered_llm_and_synth_of_one_call_share_clips_through_the_links(self):
        store = SceneStore()
        register_crowkis(name="crowkis-test", base=FAKE_BASE, synthesizer=FAKE_SYNTH,
                         session_factory=lambda: make_session(store))

        async def one_call(reply):
            task_manager = FakeTaskManager()
            llm = bolna_providers.SUPPORTED_LLM_PROVIDERS["crowkis-test"](
                language="en", model="m", provider="crowkis-test", task_manager_instance=task_manager)
            llm._inner.reply = reply
            synth = bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[FAKE_SYNTH](
                voice="nova", sampling_rate=8000, task_manager_instance=task_manager)
            chunks = [c async for c in llm.generate_stream(user_turn(QUESTION), meta_info=meta())]
            for chunk in chunks:
                await synth.push({"data": chunk.data, "meta_info": {
                    "sequence_id": 1, "turn_id": 1, "end_of_llm_stream": chunk.end_of_stream}})
            packets = []
            stream = synth.generate()
            async with contextlib.aclosing(stream), asyncio.timeout(3):
                async for packet in stream:
                    packets.append(packet)
                    if packet["meta_info"].get("end_of_synthesizer_stream"):
                        break
            task_manager.commit("r1", text_of(chunks))
            await llm.close()
            return chunks, packets, synth

        first_chunks, first_packets, _ = await one_call(LONG_ANSWER)
        self.assertEqual(first_packets[-1]["meta_info"]["format"], "mulaw")
        _wait_for_audio_stores()
        self.assertEqual(len(store.tool_writes), 1)
        _, second_packets, second_synth = await one_call("never asked")
        self.assertEqual(second_synth._inner.pushed, [])
        self.assertEqual([packet["data"] for packet in second_packets], [audio_of(pieces_of(first_chunks))])


# --- Bolna's real TaskManager ---------------------------------------------------------------

REAL_TM_NAME = "crowkis-real-tm"
REAL_TM_BASE = "crowkis-real-tm-base"
REAL_TM_ENV = {
    "OPENAI_API_KEY": "test-key",
    "AZURE_OPENAI_BASE_URL": "https://test-resource.openai.azure.com",
    "AZURE_OPENAI_API_KEY": "test-azure-key",
    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
}


def _real_task_config(provider, synthesizer="elevenlabs"):
    return {
        "task_type": "conversation",
        "toolchain": {"execution": "sequential", "pipelines": [["llm"]]},
        "tools_config": {
            "llm_agent": {
                "agent_type": "simple_llm_agent",
                "agent_flow_type": "streaming",
                "llm_config": {"model": "gpt-4o-mini", "max_tokens": 150, "provider": provider, "temperature": 0.1},
            },
            "synthesizer": {
                "provider": synthesizer,
                "provider_config": {"voice": "nova", "voice_id": "test", "model": "m", "synthesizer_key": "test-key"},
                "stream": True,
                "buffer_size": 100,
            },
            "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en", "stream": True,
                            "encoding": "linear16", "sampling_rate": 16000, "endpointing": 250},
            "input": {"provider": "default"},
            "output": {"provider": "default"},
        },
        "task_config": {},
    }


class RecordingInner(FakeInner):
    """A fake base LLM that keeps the kwargs Bolna's TaskManager built it with."""

    def __init__(self, **kwargs):
        super().__init__(**{k: v for k, v in kwargs.items() if k == "reply"})
        self.kwargs = kwargs


class RealTaskManagerTests(Base):
    """Bolna's own TaskManager builds the wrapper: it must hand over what the adapter needs."""

    def setUp(self):
        super().setUp()
        self._llms_before = dict(bolna_providers.SUPPORTED_LLM_PROVIDERS)
        self._synths_before = dict(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS)
        bolna_providers.SUPPORTED_LLM_PROVIDERS[REAL_TM_BASE] = RecordingInner
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS["elevenlabs"] = FakeSynth
        env = mock.patch.dict(os.environ, REAL_TM_ENV)
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        bolna_providers.SUPPORTED_LLM_PROVIDERS.clear()
        bolna_providers.SUPPORTED_LLM_PROVIDERS.update(self._llms_before)
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.clear()
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.update(self._synths_before)

    def build(self, store, *, synthesizer=None):
        """A real TaskManager (inside the running loop) whose LLM provider is our registration."""
        from bolna.agent_manager.task_manager import TaskManager

        def factory():
            self.session = make_session(store)
            return self.session

        register_crowkis(name=REAL_TM_NAME, base=REAL_TM_BASE, session_factory=factory, synthesizer=synthesizer)
        try:
            return TaskManager("agent", 0, _real_task_config(REAL_TM_NAME), mock.MagicMock())
        except Exception as error:  # an environment problem, not the adapter's
            self.skipTest(f"Bolna's TaskManager cannot be built here: {type(error).__name__}: {error}")

    async def test_the_task_manager_builds_our_wrapper_with_itself_and_the_agent_config(self):
        tm = self.build(SceneStore())
        llm = tm.tools["llm_agent"].llm
        self.assertIsInstance(llm, CrowkisLLM)
        self.assertIs(llm._task_manager, tm)
        self.assertIsInstance(llm._inner, RecordingInner)
        self.assertIs(llm._inner.kwargs["task_manager_instance"], tm)
        self.assertEqual(llm._inner.kwargs["provider"], REAL_TM_BASE)
        self.assertEqual(llm._agent_type(), "simple_llm_agent")

    async def test_a_turn_through_the_agent_is_decided_by_the_session_not_bypassed(self):
        tm = self.build(SceneStore())
        llm = tm.tools["llm_agent"].llm
        chunks = [c async for c in tm.tools["llm_agent"].generate(
            user_turn(QUESTION), synthesize=True, meta_info=meta())]
        self.assertEqual(text_of(chunks), ANSWER)
        self.assertEqual(llm._inner.calls[0]["messages"][-1]["content"], QUESTION)
        self.assertEqual(self.session.stats()["turns"], 1)
        await llm.close()

    async def test_the_task_manager_builds_our_synthesizer(self):
        tm = self.build(SceneStore(), synthesizer="elevenlabs")
        self.assertIsInstance(tm.tools["synthesizer"], CrowkisSynthesizer)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
