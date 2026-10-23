---
title: Pipecat
path: /docs/voice/pipecat
sdk_version: 0.5.2
---

# Crowkis in a Pipecat bot

*Crowkis SDK 0.5.2 (Python) · Pipecat 1.12 or later (tested on 1.13)*

## Add it

```bash
pip install "crowkis[pipecat]"
```

Wrap the LLM and TTS services you already have:

```python
from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS
llm = CrowkisLLM(OpenAILLMService(api_key=...))
tts = CrowkisTTS(CartesiaTTSService(api_key=..., voice_id=...))
```

Nothing else in the pipeline changes:

```python
pipeline = Pipeline([transport.input(), stt, user_aggregator, llm, tts,
                     transport.output(), assistant_aggregator])
```

## Connect to your server

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

`CrowkisLLM` builds its session from these, with live-call defaults (a 250 ms budget). To set things yourself, pass a session: `CrowkisLLM(service, session=crowkis.voice_session(...))` (with `import crowkis`).

## What happens on each turn

| The caller asks… | What Crowkis does |
|---|---|
| Something already answered, even in other words | Speaks the cached answer, so the LLM isn't called. With `CrowkisTTS` and a cached clip, the TTS isn't called either: the clip is played. |
| Something new | The LLM answers as before, reading your system prompt and keeping your tools. The answer and its audio are saved when they're safe to share. |
| Something personal ("where is my order 48213?") | The LLM answers with the whole call in view. Nothing is saved. |
| They interrupt | The half-finished answer is never saved. |

`CrowkisTTS` is optional. Without it only text is cached, and your TTS speaks every answer.

## Check it's working

```python
print(llm.session.stats())
# {'turns': 4, 'served_from_cache': 2, 'model_calls': 2, 'cache_hit_pct': 50.0, ...}
```

To see each turn as it happens, pass `on_turn=` to `CrowkisLLM`: an async callback that gets one dict with `question`, `decision`, `gate_ms` (the lookup time), `audio_cached`, `messages` and `stats`. It runs when the turn is decided, before any answer is saved, so `decision.stored` is still `False` there. To see what a hit served, print `info["decision"].text`:

```python
async def show(info):
    print(info["decision"].action, info["decision"].reason, info["decision"].text)

llm = CrowkisLLM(OpenAILLMService(api_key=...), on_turn=show)
```

## Try it without API keys

Pipecat's own test runner, a stand-in LLM that counts its calls, and a stand-in TTS. A wrapped LLM service answers with `LLMFullResponseStartFrame`, `LLMTextFrame` and `LLMFullResponseEndFrame`, as real services do:

```python
import asyncio
from dotenv import load_dotenv            # pip install python-dotenv, or set the variables in your shell
from pipecat.frames.frames import (LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame,
                                   LLMTextFrame, TTSAudioRawFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS

class FakeLLM(FrameProcessor):
    calls = 0
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            return await self.push_frame(frame, direction)
        FakeLLM.calls += 1
        for out in (LLMFullResponseStartFrame(), LLMTextFrame("We open at ten on weekdays."), LLMFullResponseEndFrame()):
            await self.push_frame(out)

class FakeTTS(FrameProcessor):
    sample_rate = 16000
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            frame = TTSAudioRawFrame(b"\x00\x00" * 160, 16000, 1)
        await self.push_frame(frame, direction)

load_dotenv()

def turn():
    return LLMContextFrame(context=LLMContext(messages=[
        {"role": "user", "content": "What time does the city museum open on weekdays?"}]))

async def main():
    llm = CrowkisLLM(FakeLLM())
    await run_test(Pipeline([llm, CrowkisTTS(FakeTTS())]),
                   frames_to_send=[turn(), SleepFrame(sleep=1.0), turn(), SleepFrame(sleep=0.5)])
    print("LLM calls:", FakeLLM.calls, llm.session.stats()["served_from_cache"])   # LLM calls: 1 1
    llm.session.agent.close()

asyncio.run(main())
```

Pipecat may log `NOT_GIVEN` settings warnings for stand-in services. They're harmless. On the first hit your TTS still speaks the answer, and its clip is kept; from the next hit on, the clip is played.

## When things go wrong

- **Server down or slow:** the turn goes to your LLM after at most 250 ms, and saving waits at most 500 ms. `cache_unavailable`, `missed_latency_budget` and `slow_writes` count these.
- **Audio cache error:** the text is still spoken by your TTS (`audio_unavailable`).
- **Caller details in the system prompt** ("You're talking to Asha Rao"): an answer that repeats them is never shared. That's safe, but you get fewer cache hits. Pass caller details with `llm.session.set_values(...)` instead.
- **Function calling:** `llm.register_function(...)` works on the wrapper. An answer built from a tool's result stays in that call.
- **Captions and transcripts:** a cached clip is played as audio only. The answer is still added to the LLM context, but RTVI captions and transcript processors don't show it.
- **History in your context:** if the `LLMContext` you start with already holds what the caller said ("I'm planning a trip to Goa"), Crowkis reads it too. A turn that tells the call something keeps the rest of the call private.
