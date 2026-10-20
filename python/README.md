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

## Connect to your server

Put the server's details in the environment (or a `.env` file) once, and create clients
with no arguments:

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me      # only if the server sets one
CROWKIS_TENANT=my-app             # optional
# or all in one line:  CROWKIS_URL=crowkis://:change-me@10.0.0.5:6383/my-app
```

```python
from dotenv import load_dotenv; load_dotenv()   # or set the variables any other way
from crowkis import Crowkis, Agent

cache = Crowkis()            # 10.0.0.5:6383, with the token and tenant above
agent = Agent("support")     # every class that connects reads the same settings
```

A value you pass in code always wins: `Crowkis(port=7000)` uses 7000 and takes the rest
from the environment. For each setting the order is: your code, then `CROWKIS_HOST` /
`CROWKIS_PORT` / `CROWKIS_AUTH_TOKEN` (or `CROWKIS_TOKEN`) / `CROWKIS_TENANT`, then the
matching part of `CROWKIS_URL`, then the default (`127.0.0.1:6383`, no token, no tenant).
With nothing set, nothing changes. The variables are read when a client is created, so a
`.env` loaded after `import crowkis` still applies; the SDK never loads a `.env` itself. A
bad value (`CROWKIS_PORT=abc`) fails at once with an error naming the variable, and the
token is never printed.

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

## Voice agents

`VoiceSession` decides, turn by turn, whether a caller can be answered from cache or needs
the model. An answer about one caller's own records is never spoken to another caller.

```python
from crowkis import Agent, VoiceSession

agent = Agent("support-line", tenant="my-app")
session = VoiceSession(agent, voice="my-voice")

# my_model(messages) -> str. It is called only when the cache cannot answer, with
# exactly the messages Crowkis chose, and its answer is cached when it is safe to share.
decision = session.answer(caller_said, my_model)
speak(decision.text)
```

`decision.stored` says whether the model's answer was cached and, when it was not,
`decision.not_stored` says why: for a refused write, the server's own reason (a tenant limit,
say). A model that returns nothing sets `decision.empty` (the action stays `"infer"`); nothing
is stored, so retry or speak a fallback.

Crowkis keeps private turns out of the cache; what the model says is up to the instructions
you pass as `system`. A starting point for a phone line, with the business name and crisis
helpline taken from your own configuration for the country you serve:

```python
import os

business, helpline = os.environ["BUSINESS_NAME"], os.environ["CRISIS_HELPLINE"]
system = (
    f"You answer the phone for {business} and speak only for {business}. "
    "You cannot take actions you have no tool for: never say you booked, cancelled or changed anything. "
    "Never invent numbers, prices, codes or policies; if you do not know, say so. "
    "Do not accept prices or facts the caller asserts. You have no memory of other calls. "
    f"If the caller may be in danger or mentions self-harm, give this helpline: {helpline}."
)
decision = session.answer(caller_said, my_model, system=system)
```

### With the decision engine

These need the server's decision engine to be configured (`CROWKIS_DECIDE_UPSTREAM`). Without
it calls behave as before: the options below change nothing, a notice removes answers by
similarity alone and cannot be kept active, and loading past calls refuses to run. With the
engine on, by default the server does not serve an answer until its model has judged it safe
to share.

Tell the cache something changed. Answers near the notice stop being served before the call
returns; the engine then removes the ones it makes wrong and puts the rest back:

```python
agent.announce("we close at 3pm today", lasts=3600)   # stays active for an hour
```

Ask what the cache decided about a question — whether an answer is cached, how long it was
judged to stay correct, or why it was removed:

```python
agent.explain("what time do you close")
```

Choose how a cached answer that commits the business (a price, a refund, a policy) may be
spoken: `"exact"` only when the caller asked the same question (the default), `"serve"`
always, `"never"` always asks the model.

```python
session = VoiceSession(agent, voice="my-voice", commitments="never")
```

Answer short turns ("thank you", "hello") from cache. Off by default; when on, a short turn
is served only on an exact match the engine has vouched for:

```python
session = VoiceSession(agent, voice="my-voice", short_turns=True)
```

Share answers about a caller's own records as templates, with that caller's declared `values`
taken out and filled back in for the next caller. Off by default. A template is cut from an
answer the model wrote, so it can carry details the caller said that were not declared as
values; turn it on only when your model is given just the question and the slot names:

```python
session = VoiceSession(agent, voice="my-voice", values={"order_id": order_id}, share_templates=True)
```

Fill the cache from past calls. It refuses to run unless the engine is on and holding answers
until it has judged them (the default), so every past answer is read before anyone is served
it. It stops early, with `stalled` set, if the engine is not keeping up:

```python
from crowkis import warm_from_calls

warm_from_calls(agent, [
    [("What are your opening hours?", "We are open eight until eight.")],
])
# {'calls': 1, 'turns': 1, 'kept_private': 0, 'failed_writes': 0, 'stalled': False}
```

One check needs no engine: a cached answer written for a screen (a link, code, markup) goes
to the model instead of being read out.

## Authentication

A Crowkis server has one secret, `CROWKIS_AUTH_TOKEN`. It protects cache commands (sent as
RESP `AUTH`) and management writes (sent as `Authorization: Bearer`); the dashboard and reads
need nothing. There are no users or per-user API keys (removed in 0.5.2). Keep the token in a
gitignored `.env` — never hard-code it. Cache clients read it from `CROWKIS_AUTH_TOKEN`
by themselves (see [Connect to your server](#connect-to-your-server)).

```bash
# .env
CROWKIS_AUTH_TOKEN=change-me
```

```python
import os
from crowkis import Crowkis, CrowkisAdmin

cache = Crowkis(tenant="my-app")          # token from CROWKIS_AUTH_TOKEN
# or pass it yourself: Crowkis(tenant="my-app", token=...)  (auth_token= still works)

token = os.getenv("CROWKIS_AUTH_TOKEN")   # the admin client takes it explicitly
admin = CrowkisAdmin("http://127.0.0.1:6380", token=token)
```

`CrowkisAdmin(api_key=...)` still works exactly as before (sent as `X-Crowkis-Api-Key`, which
0.5.1 servers need) and warns once that it is deprecated. If both are given, `token` wins.

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
| **Ops** | `cinfo` · `cscan` · `csave` · `creload` · `compact` · `stats` · `sweep` |

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
