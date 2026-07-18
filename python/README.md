# Crowkis Python SDK

Official Python client for Crowkis — an intelligent, Redis-compatible cache and
memory layer for LLM apps and AI agents. Stop paying twice for answers you already have.

## Install

```bash
pip install crowkis
```

That's it — zero dependencies. (LangChain/OpenAI adapters use those libraries if you
already have them; nothing extra to install.)

## Discover everything

```python
import crowkis
crowkis.help()            # grouped cheat-sheet of every feature
crowkis.help("memory")    # just the agent-memory commands
```

## Server Defaults

If you start Crowkis with:

```bash
./target/release/crowkis server --port 6383 --data ./crowkis.data
```

then the default ports are:

- RESP: `6383`
- dashboard / management HTTP: `6384`

## Quick Start

```python
from crowkis import CrowkisClient

cache = CrowkisClient(host="127.0.0.1", port=6383, tenant="demo", model="gpt-4o")

answer = cache.get_or_compute(
    "Explain vector caches",
    lambda query: call_llm(query),
    ttl=3600,
)

print(answer.decode("utf-8", errors="replace"))
cache.close()
```

## LangChain / LangGraph — semantic LLM cache (2 lines)

```python
from langchain_core.globals import set_llm_cache
from crowkis.integrations.langchain import CrowkisCache

set_llm_cache(CrowkisCache(tenant="my-app", ttl=3600))
# every LangChain / LangGraph model call now checks Crowkis first;
# rephrased prompts still hit — that's the token savings.
```

## Agent memory (any framework — LangGraph, CrewAI, AutoGen, custom)

```python
from crowkis import CrowkisMemory

mem = CrowkisMemory(agent="support-bot", user="alice")
mem.remember("Alice prefers email over phone")
hits = mem.recall("how should I contact Alice?")   # semantic recall
```

## Drop-in OpenAI (change 2 lines)

```python
from crowkis import CachedOpenAI

client = CachedOpenAI(tenant="my-app")              # was: OpenAI()
resp = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
```

## Semantic Cache

```python
from crowkis import CrowkisClient

cache = CrowkisClient(host="127.0.0.1", port=6383, tenant="demo", model="gpt-4o")

cache.cset(
    "Explain vector caches",
    "Explain vector caches as reusable cached answers for similar queries.",
    ttl=3600,
)

cached = cache.cget("Explain vector caches")
print(cached.decode("utf-8", errors="replace") if cached else "miss")
cache.close()
```

## Streaming Cache

```python
from crowkis import AsyncCrowkisClient

async with AsyncCrowkisClient(host="127.0.0.1", port=6383, tenant="demo", model="gpt-4o") as cache:
    async for chunk in cache.stream_get_or_compute(
        "Explain vector caches",
        lambda query: openai_stream(query),
        ttl=3600,
        chunk_tokens=4,
        delay_ms=20,
    ):
        print(chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk, end="")
```

## Multi-Modal Cache

```python
from pathlib import Path

from crowkis import CrowkisClient

image = Path("receipt.png").read_bytes()
cache = CrowkisClient(host="127.0.0.1", port=6383, tenant="demo", model="gpt-4o-vision")

cache.cset(
    "What is the total on this receipt?",
    "The receipt total is $42.15.",
    ttl=3600,
    image=image,
)

cached = cache.cget("What is the total on this receipt?", image=image)
print(cached.decode("utf-8", errors="replace") if cached else "miss")
cache.close()
```

## Image-Only Lookup

```python
answer = cache.cimgget(image, tenant="demo")
```

## gRPC API

```python
from crowkis import CrowkisGrpcStub

grpc_cache = CrowkisGrpcStub("127.0.0.1:6381")
grpc_cache.set(
    "Explain vector caches",
    "Explain vector caches as reusable cached answers for similar queries.",
    tenant="demo",
    model="gpt-4o",
    ttl=3600,
)

hit = grpc_cache.get("Explain vector caches", tenant="demo")
print(hit.text)
grpc_cache.close()
```

Install `grpcio` to use the gRPC helper. RESP users do not need it.

## Management API

Management helpers talk to the dashboard / management HTTP port, usually `6384` when the RESP server is on `6383`.
