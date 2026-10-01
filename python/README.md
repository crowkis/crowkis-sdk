<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/banner.png" alt="Crowkis — the intelligent cache & memory for LLM apps, built in Rust" width="100%" />

<p>
<a href="https://pypi.org/project/crowkis/"><b>PyPI</b></a> &nbsp;·&nbsp;
<b>Python 3.9+</b> &nbsp;·&nbsp;
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker</b></a> &nbsp;·&nbsp;
<b>Apache 2.0</b>
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> &nbsp;·&nbsp;
<a href="https://www.crowkis.com/docs/sdk-python"><b>Documentation</b></a> &nbsp;·&nbsp;
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker Hub</b></a>
</p>

</div>

## About Crowkis

Every LLM app quietly pays the same bill twice. Users ask the same questions worded a
hundred different ways, and each rewording is billed at full price. **Crowkis is an
intelligent, Redis-compatible cache and memory layer that sits between your app and your
model** — it recognises when a new question *means* the same as one it has already
answered, and serves that answer instantly, for free.

It is **model-agnostic**: you wrap the call you already make — to OpenAI, Anthropic, a
local model, or whatever comes next — and Crowkis handles the rest. It also gives your
agents **durable, semantic memory** that survives restarts and stays strictly isolated
per tenant. The engine is written in Rust, ships as a single small container, and
understands your prompts entirely on your own machine — no prompts ever leave your box
just to be understood.

This is the official **Python SDK**. It has zero required dependencies.

## Install

```bash
pip install crowkis
```

## Run a Crowkis server

```bash
docker run -d -p 6383:6383 -v "$(pwd)/.crow:/data/.crow" \
  crowkis/crowkis:latest server --data /data/.crow
```

The server listens on `6383` (cache/RESP), `6384` (dashboard/HTTP), and `6385` (gRPC).
Image → [hub.docker.com/r/crowkis/crowkis](https://hub.docker.com/r/crowkis/crowkis).

## Cache any model — the decorator

The simplest way in. Decorate any function whose first argument is the prompt. It works
like `functools.lru_cache`, but matches on **meaning**, so rephrased prompts hit too. The
body can call *any* provider.

```python
from crowkis import Crowkis

cache = Crowkis(tenant="my-app")

@cache.cached(ttl=3600)
def answer(prompt: str) -> str:
    return my_model(prompt)          # OpenAI, Anthropic, a local model — anything

answer("How do refunds work?")       # miss → your model runs, result cached
answer("What's the refund process?") # semantic HIT → no model call, instant
```

Prefer an inline call over a decorator?

```python
text = cache.ask("How do refunds work?", compute=lambda p: my_model(p), ttl=3600)
```

## Read & write directly

Full control over what gets read and written:

```python
hit = cache.lookup("what's the refund timeline?")   # semantic match
if hit:
    print(hit.text, hit.similarity, hit.confidence)
else:
    cache.store("what's the refund timeline?", "5–7 business days.", ttl=3600)
```

## Streaming

Serve a cached answer in chunks so a hit feels like live model output:

```python
from crowkis import AsyncCrowkis

async with AsyncCrowkis(tenant="my-app") as cache:
    async for chunk in cache.stream("Explain vector caches", compute=my_stream, ttl=3600):
        print(chunk, end="")
```

## LangChain & LangGraph

Set it once and every LangChain (and LangGraph) model call is cached by meaning — no chain
changes. This mirrors LangChain's own `set_llm_cache` pattern, so it is a true drop-in.

```python
from langchain_core.globals import set_llm_cache
from crowkis.integrations.langchain import CrowkisCache

set_llm_cache(CrowkisCache(tenant="my-app", ttl=3600))
```

## Agent memory

Durable, semantic, per-user memory for agents — LangGraph, CrewAI, AutoGen, or your own
loop. Every recall is scoped to its agent and user, so no tenant can ever read another's
memory.

```python
from crowkis import CrowkisMemory

mem = CrowkisMemory(agent="support-bot", user="alice")
mem.remember("Alice prefers email over phone")
mem.recall("how should I contact Alice?")   # semantic recall
```

## Conversations: chat and voice agents

A model that reads the whole conversation writes answers that can carry what one person
said ("Thanks Rahul, premium members get it tomorrow"). Cached as the answer to "how long
does shipping take?", that reaches the next person. A `Conversation` decides, per turn,
what the model may read and whether its answer is shared, so that cannot happen:

| Turn | The model reads | Answer |
| --- | --- | --- |
| General ("How long does shipping take?") | the question alone | shared |
| Follow-up ("How long does it take?") | the previous question + this one | shared, keyed by both |
| Personal ("Where is my order?", "I'm a farmer, what suits me?") | the whole conversation | never shared |
| A non-answer ("Could you tell me the destination?") | | never saved |

It does no I/O, so any pipeline can use it with its own client and storage:

```python
from crowkis import Conversation

conv = Conversation(max_turns=20)          # one per chat thread or call
plan = conv.plan(user_message)
if plan.action == "lookup":
    hit = my_cache_lookup(plan.key, threshold=plan.threshold)
    if hit:
        reply = conv.served(plan, hit)
answer = my_model(conv.model_messages(plan, system=SYSTEM_PROMPT))   # on a miss
saving = conv.settle(plan, answer)
if saving.write:
    my_cache_store(saving.key, saving.text)    # saving.outcome says why when it is not
```

`crowkis.is_personal()`, `is_context_dependent()` and `is_non_answer()` expose the rules
underneath. They are identical in the Node SDK and mirrored in the Crowkis server.

**Voice agents.** `VoiceSession` is that policy plus a voice pipeline: lookups under a
hard latency budget, cached audio per voice, fillers and barge-in.

```python
from crowkis import Agent, VoiceSession

session = VoiceSession(Agent("support", tenant="my-app"), voice="sarvam/bulbul:v3/priya",
                       latency_budget_ms=300)
decision = session.answer(transcript, my_llm, system=SYSTEM_PROMPT)   # cache, or the model
speak(decision.text, decision.audio)
```

For Pipecat, `crowkis.integrations.pipecat.crowkis_processors()` puts the cache in front of
the LLM and the TTS (`pip install "crowkis[pipecat]"`). A speech-to-speech model that holds
the whole call itself records with `session.record_private_turn()`: never shared.

## Authentication

If your server sets an auth token (`CROWKIS_AUTH_TOKEN`), pass it from your environment —
never hard-code it. Keep it in a gitignored `.env`.

```python
import os
from crowkis import Crowkis

cache = Crowkis(
    host=os.getenv("CROWKIS_HOST", "127.0.0.1"),
    port=int(os.getenv("CROWKIS_PORT", "6383")),
    tenant="my-app",
    auth_token=os.getenv("CROWKIS_TOKEN"),   # from .env, not the code
)
```

## Discover every command

```python
import crowkis
crowkis.help()            # grouped cheat-sheet of every feature
crowkis.help("memory")    # filter by topic
```

## Method reference

| Group | Methods |
|-------|---------|
| **Caching** | `cached()` · `ask()` · `stream()` · `lookup()` · `store()` · `similar()` · `embed()` · `flush()` |
| **Agent memory** | `remember` · `recall` · `extract` · `history` · `as_of` · `forget` · `link` · `graph` |
| **Sessions / docs / pins / tools** | `csession_*` · `cdoc_*` · `cpin*` · `ctool*` |
| **Safety & quality** | `cguard` · `coutcheck` · `cflag` · `ccheckbad` |
| **Cost / limits / compliance** | `cbudget_*` · `ckeylimit_*` · `cpii_*` · `cdedup` |
| **Evals / prompts / freshness** | `ceval` · `cprompt_*` · `csource_*` · `cstale` · `cinvalidate` |
| **Ops** | `cinfo` · `cscan` · `csave` · `creload` · `compact` |

Full reference and guides at **[www.crowkis.com/docs/sdk-python](https://www.crowkis.com/docs/sdk-python)**.

## Contributing

Issues and pull requests are welcome at
[github.com/crowkis/crowkis-sdk](https://github.com/crowkis/crowkis-sdk). The client is
Apache-2.0 licensed and safe to fork, embed, and ship.

<br/>

<table>
<tr>
<td width="96"><img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/founder.jpg" width="84" alt="Mohit Rohilla" /></td>
<td>
Built with care by <b><a href="https://github.com/itsmohitrohilla">Mohit Rohilla</a></b>, founder & creator of Crowkis — engineering the intelligent cache & memory layer for the agentic era, in Rust. 🦀
</td>
</tr>
</table>

<sub>© 2026 Crowkis · Licensed under Apache-2.0 · <a href="https://www.crowkis.com">crowkis.com</a></sub>
