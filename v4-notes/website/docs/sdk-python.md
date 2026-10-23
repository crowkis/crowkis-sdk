---
title: Python SDK
path: /docs/sdk-python
sdk_version: 0.5.2
---

# Python SDK

*`crowkis` 0.5.2 · Python 3.9+ · works with server 0.5.2*

## Install

```bash
pip install crowkis                 # the client: no dependencies
pip install "crowkis[pipecat]"      # + Pipecat voice bots
pip install "crowkis[livekit]"      # + LiveKit Agents voice bots
pip install "crowkis[langchain]"    # + LangChain / LangGraph cache
pip install "crowkis[openai]"       # + the OpenAI helpers
pip install "crowkis[grpc]"         # + the gRPC client
```

## The one idea

Ask Crowkis before you ask your model. If someone already asked the same thing, even in other words, you get the stored answer and the model isn't called. If not, your model answers and Crowkis keeps the answer for next time.

## Connect

Put the server's details in the environment once:

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
# the server's token, if it sets one
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

```python
from crowkis import Crowkis

cache = Crowkis()                 # every client reads the settings above
```

A value passed in code wins: `Crowkis(host="10.0.0.6", port=7000, tenant="other", auth_token=...)`. With nothing set, the client uses `127.0.0.1:6383`. The SDK doesn't load `.env` files itself; use `python-dotenv` or your platform. See [Configuration](/docs/configuration#sdk-settings).

`Crowkis` is the same class as `CrowkisClient`. For asyncio, use `AsyncCrowkis`.

## Cache any model: the decorator

```python
@cache.cached(ttl=3600)
def answer(prompt: str) -> str:
    return my_model(prompt)          # OpenAI, Anthropic, a local model: anything

answer("How do refunds work?")       # miss: your model runs, the answer is kept
answer("What's the refund process?") # a hit by meaning: no model call
```

Or inline: `cache.ask("How do refunds work?", compute=my_model, ttl=3600)`. (`get_or_compute` is the older name of `ask` and still works.)

## Read and write directly

```python
hit = cache.lookup("what's the refund timeline?")
if hit:
    print(hit.text, hit.similarity, hit.confidence)
else:
    cache.store("what's the refund timeline?", "5–7 business days.", ttl=3600)
```

## Streaming

```python
from crowkis import AsyncCrowkis

async with AsyncCrowkis(tenant="my-app") as cache:
    async for chunk in cache.stream("Explain vector caches", compute=my_stream, ttl=3600):
        print(chunk, end="")
```

## LangChain and LangGraph

```python
from langchain_core.globals import set_llm_cache
from crowkis.integrations.langchain import CrowkisCache

set_llm_cache(CrowkisCache(tenant="my-app", ttl=3600))   # every model call now checks Crowkis first
```

## Agent memory

```python
from crowkis import CrowkisMemory

mem = CrowkisMemory(agent="support-bot", user="alice")
mem.remember("Alice prefers email over phone")
mem.recall("how should I contact Alice?")
```

## Chat apps

`Chat` handles follow-ups safely. "Is it safe?" after "I'm allergic to peanuts" is looked up as "Is pad thai safe for someone with a peanut allergy?", never as the bare question.

`complete(messages) -> str` is your model: it takes OpenAI-style messages and returns the reply. `messages` is the whole chat so far, and `thread_id` names the conversation.

```python
from crowkis import Agent, Chat, LLMUnderstander

chat = Chat(Agent("support-bot"), LLMUnderstander(complete), system="You are Acme's assistant.")
reply = chat.turn(thread_id, messages, answer=complete)   # messages: the whole chat so far
print(reply.text, reply.outcome)                           # served | saved | not_shared | refused:<why>
```

Anything personal, urgent, part of a booking or unclear is answered with the whole chat and never cached. Keep user details out of `system`: an answer that repeats one is answered but never saved (`refused:prompt_detail`).

## Voice agents

See [Voice agents](/docs/voice) for Pipecat, LiveKit and your own loop. In short:

```python
import crowkis

session = crowkis.async_voice_session()                 # one per phone call
stream = await session.respond(caller_said, my_llm)     # cached, or your LLM's words as they arrive
```

## Authentication

The server has one secret, `CROWKIS_AUTH_TOKEN`. The cache clients send it for you when it's in the environment, or when you pass `token=` (`auth_token=` works too). The admin client takes it explicitly:

```python
import os
from crowkis import CrowkisAdmin

admin = CrowkisAdmin("http://127.0.0.1:6384", token=os.environ["CROWKIS_AUTH_TOKEN"])
```

## Discover every command

```python
import crowkis
crowkis.help()            # every feature, grouped
crowkis.help("memory")    # one topic
```

## Method reference

```text
cache.cached(ttl=, threshold=)      # decorator: cache any function's model call
cache.ask(prompt, compute=, ttl=)   # the stored answer, or compute() and keep it
cache.stream(prompt, compute=)      # the same, in chunks (AsyncCrowkis)
cache.lookup(prompt)                # CacheHit(text, similarity, confidence) or None
cache.store(prompt, answer, ttl=)   # keep an answer for a prompt
cache.similar(prompt, k=10)         # the k closest stored prompts
cache.flush()                       # clear this tenant's cache

mem.remember(fact, ttl=)  ·  mem.recall(query, k=5)  ·  mem.extract(conversation)
mem.history(query, k=5)   ·  mem.forget(query=)      ·  mem.link(subj, rel, obj)  ·  mem.graph(entity, depth=)

admin.get_stats()  ·  admin.health()  ·  admin.flush_tenant(tenant_id)  ·  admin.invalidate_source(source_id)
```
