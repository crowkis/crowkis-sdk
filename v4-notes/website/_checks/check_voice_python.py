"""Runs the Python voice pages' code against a real Crowkis server (CROWKIS_* in the
environment), with a stand-in LLM and TTS. Exit 0 when every page's code does what the
page says. Run with the venv that has the framework for the Pipecat / LiveKit checks:

    python check_voice_python.py core|pipecat|livekit
"""
import asyncio
import sys
import uuid

import crowkis

SYSTEM = "You are Acme's phone assistant. Be brief."
WHICH = sys.argv[1] if len(sys.argv) > 1 else "core"
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# -- custom-loop-python.md: "The whole loop", as written -----------------------------------
_r = __import__("random").SystemRandom()
TOPIC = "the " + " ".join("".join(_r.choice("bcdfghjklmnpqrstvwxz") + _r.choice("aeiou") for _ in range(4)) for _ in range(2)) + " widget"
QUESTION = f"how do I reset {TOPIC}"
llm_calls = []


async def my_streaming_llm(messages):  # the page's OpenAI shape, without OpenAI
    llm_calls.append(messages)
    for piece in ["Hold the button ", "for five seconds."]:
        yield piece


async def caller_turns():
    yield QUESTION


spoken, played = [], []


class tts:
    @staticmethod
    async def send(piece):
        spoken.append(piece)


async def play(audio):
    played.append(audio)


def caller_interrupted():
    return False


async def run_call(caller_turns):                     # your STT's final transcripts
    session = crowkis.async_voice_session()            # one per call
    try:
        async for said in caller_turns:
            stream = await session.respond(said, my_streaming_llm, system=SYSTEM)
            if stream.decision.audio:                  # a cached answer with its audio
                await play(stream.decision.audio)      # no TTS
                continue
            async for piece in stream:                 # cached text, or the LLM's words as they arrive
                if caller_interrupted():
                    session.cancel()                   # stops the LLM; nothing is saved
                    break
                await tts.send(piece)
            await stream.close()
        return session.stats()
    finally:
        await session.close()


async def custom_loop():
    first = await run_call(caller_turns())
    await asyncio.sleep(2)
    second = None
    for _ in range(3):
        second = await run_call(caller_turns())
        if second["served_from_cache"]:
            break
        await asyncio.sleep(2)
    # A shared real server may already know a near-identical question from an earlier run.
    check("custom loop: the first caller's turn was answered", first["model_calls"] + first["served_from_cache"] == 1, str(first)[:80])
    check("custom loop: a later caller is served from the cache", second["served_from_cache"] == 1, str(second)[:80])
    check("custom loop: the stats keys the page shows exist",
          all(k in second for k in ("turns", "served_from_cache", "model_calls", "cache_hit_pct", "cache_unavailable",
                                    "missed_latency_budget", "slow_writes", "audio_unavailable")))
    check("custom loop: the caller heard the answer", "".join(spoken).startswith("Hold the button for five seconds."))


# -- pipecat.md ----------------------------------------------------------------------------
async def pipecat():
    from types import SimpleNamespace

    from pipecat.frames.frames import LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.tests.utils import SleepFrame, run_test

    from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS

    class OpenAILLMService(FrameProcessor):  # stand-in with the same role
        def __init__(self, **kw):
            super().__init__()
            self._settings = SimpleNamespace(system_instruction=None)
            self.calls = 0

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, LLMContextFrame):
                self.calls += 1
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(LLMTextFrame("Hold the button for five seconds."))
                await self.push_frame(LLMFullResponseEndFrame())
            else:
                await self.push_frame(frame, direction)

    class CartesiaTTSService(FrameProcessor):
        sample_rate = 16000

        def __init__(self, **kw):
            super().__init__()
            self._settings = SimpleNamespace(voice="v")

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)   # speaks nothing; passes every frame on

    question = f"how do I pair {TOPIC} with my phone"
    calls = []
    for _ in range(4):
        service = OpenAILLMService(api_key="...")
        llm = CrowkisLLM(service)                                   # as on the page
        tts = CrowkisTTS(CartesiaTTSService(api_key="...", voice_id="..."))
        ctx = LLMContextFrame(context=LLMContext(messages=[{"role": "user", "content": question}]))
        await run_test(Pipeline([llm, tts]), frames_to_send=[ctx, SleepFrame(0.3)])
        calls.append(service.calls)
        stats = llm.session.stats()                                 # the page's check
        await asyncio.to_thread(llm.session.agent.close)
        if len(calls) > 1 and service.calls == 0:
            break
        await asyncio.sleep(2)
    check("pipecat: CrowkisLLM(service) builds its session from the environment", stats["turns"] == 1, str(calls))
    check("pipecat: a later caller is served without the LLM", calls[-1] == 0, str(calls))
    check("pipecat: llm.session.stats() has served_from_cache", "served_from_cache" in stats)


# -- livekit-python.md ---------------------------------------------------------------------
async def livekit():
    from types import SimpleNamespace
    from unittest import mock

    from livekit.agents import Agent, llm as lk_llm
    from livekit.agents.voice.agent import ModelSettings

    from crowkis.integrations.livekit import CrowkisVoice

    class Assistant(CrowkisVoice, Agent):                           # as on the page
        def __init__(self):
            super().__init__(instructions="You are Acme's phone assistant.")

    question = f"how do I charge {TOPIC}"
    llm_calls = []

    async def own_llm(agent, chat_ctx, tools, model_settings):
        llm_calls.append(1)
        yield "Use the cable in the box."

    async def own_tts(agent, text, model_settings):
        async for _ in text:
            pass
        return
        yield

    results = []
    with mock.patch.multiple(Agent.default, llm_node=own_llm, tts_node=own_tts):
        for _ in range(4):
            agent = Assistant()
            agent._crowkis_tts = lambda: SimpleNamespace(sample_rate=16000, num_channels=1, voice="v")
            ctx = lk_llm.ChatContext([lk_llm.ChatMessage(role="system", content=["You are Acme's phone assistant."]),
                                      lk_llm.ChatMessage(role="user", content=[question])])
            before = len(llm_calls)
            said = "".join([c if isinstance(c, str) else "" async for c in agent.llm_node(ctx, [], ModelSettings())])
            stats = agent.crowkis.stats()                           # the page's check
            results.append(len(llm_calls) - before)
            await agent.crowkis.close()
            if len(results) > 1 and results[-1] == 0:
                break
            await asyncio.sleep(2)
    check("livekit: the first call was answered", results[0] in (0, 1) and said, str(results))
    check("livekit: a later call is served from the cache", results[-1] == 0, f"{results} {said!r}")
    check("livekit: self.crowkis.stats() has served_from_cache", "served_from_cache" in stats)


asyncio.run({"core": custom_loop, "pipecat": pipecat, "livekit": livekit}[WHICH]())
print(f"{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
