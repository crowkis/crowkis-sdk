---
title: LiveKit Agents (Python)
path: /docs/voice/livekit-python
sdk_version: 0.5.2
---

# Crowkis in a LiveKit agent (Python)

*Crowkis SDK 0.5.2 (Python) · livekit-agents 1.8 (tested on 1.8.8)*

## Add it

```bash
pip install "crowkis[livekit]"
```

Put `CrowkisVoice` first in your agent class:

```python
from livekit.agents import Agent
from crowkis.integrations.livekit import CrowkisVoice
class Assistant(CrowkisVoice, Agent): ...
```

Your STT, LLM and TTS plugins and your `AgentSession` stay exactly as they are.

## Connect to your server

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

Each agent (one per call) builds its own `crowkis.async_voice_session()` from these, with live-call defaults. To change the options, set `crowkis_options = {...}` on the class. To pass your own session, pass `crowkis=` through to `super().__init__(...)`: for example `def __init__(self, **kwargs): super().__init__(instructions="...", **kwargs)`, then `Assistant(crowkis=crowkis.async_voice_session(...))`.

## What happens on each turn

| The caller asks… | What Crowkis does |
|---|---|
| Something already answered | Speaks the cached answer without the LLM, and with its cached audio, without the TTS. |
| Something new | Your LLM answers through LiveKit's own `llm_node`, reading your instructions and the caller's question, with your tools. The answer and its audio are saved when they're safe to share. |
| Something personal | The LLM reads the whole call. Nothing is saved. |
| They interrupt, or LiveKit drops a preemptive reply | Nothing is saved. |
| A turn with RAG or CRM data in the context | The LLM reads all of it. The answer stays in that call. |

## Check it's working

```python
print(self.crowkis.stats())   # inside your agent, e.g. in on_exit()
# {'turns': 6, 'served_from_cache': 3, 'model_calls': 3, 'cache_hit_pct': 50.0, ...}
```

## Try it without a room or API keys

Give a text-only `AgentSession` a stand-in LiveKit LLM, and run two identical turns. `CrowkisVoice` calls LiveKit's own `llm_node`, which uses the session's LLM, so a stand-in LLM is the way to test (not a base class with its own `llm_node`):

```python
import asyncio
from dotenv import load_dotenv            # pip install python-dotenv, or set the variables in your shell
from livekit.agents import Agent, AgentSession, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from crowkis.integrations.livekit import CrowkisVoice

load_dotenv()

class FakeLLM(llm.LLM):
    calls = 0
    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_):
        FakeLLM.calls += 1
        return FakeStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)

class FakeStream(llm.LLMStream):
    async def _run(self):
        self._event_ch.send_nowait(llm.ChatChunk(id="c1", delta=llm.ChoiceDelta(role="assistant",
                                                 content="We open at ten on weekdays.")))

class Assistant(CrowkisVoice, Agent):
    def __init__(self):
        super().__init__(instructions="You are Acme's phone assistant.")

async def main():
    agent = Assistant()
    async with AgentSession(llm=FakeLLM()) as session:
        await session.start(agent)
        for _ in range(2):
            await session.run(user_input="What time does the city museum open on weekdays?")
            await asyncio.sleep(1)
        print("LLM calls:", FakeLLM.calls, agent.crowkis.stats()["served_from_cache"])   # LLM calls: 1 1
        await agent.crowkis.close()

asyncio.run(main())
```

## When things go wrong

- **Server down or slow:** the turn goes to your LLM after at most 250 ms, and saving waits at most 500 ms. See `cache_unavailable`, `missed_latency_budget` and `slow_writes`.
- **Audio cache error:** the text is still spoken (`audio_unavailable`).
- **Your own `llm_node` / `tts_node`:** call `super()` in them, or Crowkis is skipped.
- **Instructions with caller details** ("The caller is Asha Rao"): an answer that repeats them is never shared. Keep caller details out of the instructions to get more hits.
- **Earlier messages in `chat_ctx`:** Crowkis reads them too. A caller line that tells the call something ("I'm planning a trip to Goa") keeps the rest of the call private.
