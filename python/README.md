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
docker run -d --name crowkis -p 127.0.0.1:6383:6383 -p 127.0.0.1:6384:6384 -e CROWKIS_PROTECTED_MODE=off -e CROWKIS_MANAGEMENT_BIND_HOST=0.0.0.0 -v crowkis-data:/data crowkis/crowkis:latest
# Reachable from this machine only. To serve other machines, publish 6383 and set
# -e CROWKIS_AUTH_TOKEN=<a long random secret> instead of CROWKIS_PROTECTED_MODE=off.
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

`ttl` is in seconds; `None` or `0` sends no lifetime, so the server applies its default
lifetime for that kind of question. An answer holding personal details its
question does not name is never served, so the server does not keep it: the call returns as
usual and the `crowkis` logger warns once per reason. Store such an answer with
`template=True` and `{slot}` placeholders to cache its shape.

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

`mem.extract(transcript)` takes text of any length: long text is sent in parts the server
accepts (under 64 KiB and 64 facts each), in order, and the facts come back as one list.

## Chat apps

A chat turn often depends on what the user said earlier ("I'm allergic to peanuts", then
"is pad thai safe?"). `Chat` turns each message into one stand-alone question that carries
it ("Is pad thai safe for someone with a peanut allergy?"), checks it with fixed rules,
looks it up, and on a miss lets your model answer that question alone, so the answer can be
shared. Anything personal, urgent, part of a booking or unclear is answered with the whole
chat and never cached.

```python
from crowkis import Agent, Chat, CrowkisClient, LLMUnderstander

agent = Agent("support-bot", client=CrowkisClient(tenant="acme"))
chat = Chat(agent, LLMUnderstander(complete), system="You are Acme's assistant.")

reply = chat.turn(thread_id, messages, answer=complete)   # messages: the whole chat
print(reply.text, reply.from_cache, reply.outcome, reply.reason)
```

`complete(messages) -> str` is your model; the same function does both jobs (reading each turn
into a question, and answering). `reply.outcome` is `served` (from the cache), `saved` (answered
and shared), `not_shared` (answered for this user only; `reply.reason` says why) or
`refused:<why>` (answered, but the answer was not kept). If the cache cannot be reached the user
still gets the model's answer, with `outcome` `refused:write_failed`. Keep a user's details out of
`system`: an answer that repeats one ("Hi Asha! ...") is answered but never saved
(`refused:prompt_detail`). Per thread, `Chat` keeps a small memory (facts,
topic, reply language), never the transcript; pass `store=` with `load`/`save` to keep it
across several servers. The reply language is part of the cache identity: a Hindi chat never
gets the English answer.

## Voice agents

`VoiceSession` decides, turn by turn, whether a caller can be answered from cache or needs
the model. An answer about one caller's own records is never spoken to another caller.

```python
import crowkis

session = crowkis.voice_session()     # server settings from the environment

# my_model(messages) -> str. It is called only when the cache cannot answer, with
# exactly the messages Crowkis chose, and its answer is cached when it is safe to share.
decision = session.answer(caller_said, my_model)
speak(decision.text)
```

`voice_session()` builds the connection and the agent for you, with defaults for a live
call, where a caller is waiting:

| Setting | Default | Why |
|---|---|---|
| `latency_budget_ms` | `250` | The longest a turn waits for a cache lookup before it asks the model. `None` turns it off. |
| `timeout` | `1.0` s, no retries | A request to a stuck server gives up within a second, not ~15 s. Saving the model's answer waits at most twice the latency budget (500 ms); a slower save finishes in the background, and the answer is reported as `slow_write` (`stats()["slow_writes"]`). The cost: a request that fails once (the first on a connection after a server restart, or a `BUSY` reply) is not retried, so that turn goes to the model or that answer isn't stored. |
| `agent_id` | `"voice"` | The agent the session's cache belongs to. |
| server | from the environment | `host=`, `port=`, `auth_token=`, `tenant=` still win; or pass your own `client=`. |

`voice=` is your TTS voice id. Without it the session caches text only and never reads or
stores audio, so two voices can never share a clip. To cache audio too:

```python
session = crowkis.voice_session(voice="eleven-rachel", synthesise=my_tts)
```

Every other `VoiceSession` option (`serve_above`, `fillers`, `ttl`, `values`, ...) can be
passed to `voice_session()` as well. For bulk work such as `warm_from_calls`, build an
`Agent` with an ordinary client rather than reusing the session's live-call one. To build
it yourself, as before:

```python
from crowkis import Agent, VoiceSession

agent = Agent("support-line", tenant="my-app")
session = VoiceSession(agent, voice="my-voice")   # no budget, 5 s timeout with 2 retries
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

### Cached audio

With `voice=` and `synthesise=`, a cached answer comes with its audio
(`decision.audio`), so the next caller who asks skips the TTS too. Two things to know:

- **Audio never breaks a call.** If the audio cache can't be read or written, or your own
  `synthesise` fails, the turn still gets its text (`decision.audio` is `None`) and your
  TTS speaks it. Failures are logged and counted (`stats()["audio_unavailable"]`,
  `agent.audio_errors`).
- **Name the audio format when your bots differ.** A clip is only reused for the same
  voice, language, speed and `audio_format`. If a phone bot (8 kHz) and a web bot (24 kHz)
  share a voice, set `audio_format="pcm16-8000"` / `"pcm16-24000"` so neither plays the
  other's clip. The Pipecat processors name the sample rate for you (Pipecat bots that
  used the basic audio cache before 0.5.2 make each clip once more, under the new key).

### Streaming the answer

Voice bots send the model's words to the TTS as they arrive, so the caller hears a reply
sooner. `respond()` does that and still caches the answer:

```python
stream = session.respond(caller_said, my_streaming_model)
if stream.decision.audio:              # a cached answer with its audio: play it, skip the TTS
    play(stream.decision.audio)
else:
    for piece in stream:               # cached text, or the model's words as they arrive
        tts.send(piece)
```

`my_streaming_model(messages)` returns the model's text pieces as it writes them (any
iterable of `str`), or the whole answer as one `str`. With an OpenAI-style client:

```python
def my_streaming_model(messages):
    # `with` closes the HTTP stream when respond() stops early, so no more tokens are billed.
    with client.chat.completions.create(model="gpt-4o-mini", messages=messages, stream=True) as chunks:
        for chunk in chunks:
            if chunk.choices:
                yield chunk.choices[0].delta.content
```

The model is only called when the cache can't answer, and only with the messages Crowkis
chose. When its stream ends, the full answer is saved under the same rules as `answer()`
(`stream.decision.stored` / `not_stored` say what happened). If the caller talks over the
answer, call `session.cancel()`: the stream stops at the next piece, the model's stream is
closed (no more tokens billed) and nothing is saved. The same happens when the caller says
something new (`decide()` / `respond()` again). If the model fails mid-stream, the error is
raised and nothing is saved; leaving the loop early or `stream.close()` saves nothing too.
`respond()` takes `system=` and `private=` like `answer()` and `record()`.

### In an async app (asyncio)

Voice frameworks run on asyncio, where a blocking call stalls every other call on the
loop. Use the async session there: the same rules, with every wait off the event loop.

```python
import crowkis

session = crowkis.async_voice_session()      # voice_session(), for asyncio

decision = await session.answer(caller_said, my_model)          # async or sync model

stream = await session.respond(caller_said, my_streaming_model) # async or sync stream
async for piece in stream:
    await tts.send(piece)
```

`decide`, `answer`, `record`, `respond`, `report_stats` and `close` are coroutines.
`cancel()`, `stats()`, `injections()`, `set_values()` and the rest stay plain calls, since
they never wait; setting an attribute (`session.latency_budget_ms = 400`) changes the
session underneath. Your model can be `async` (awaited on the loop) or a normal function
(run on a thread pool, so a blocking SDK call doesn't stall the loop); a stream can be an
async iterable or a normal one.

Server calls run on a shared pool of 64 threads, which serves far more than 64 calls at
once because each wait is capped by the latency budget and the 1 s timeout. A blocking
(sync) model runs on a separate pool of 256 threads, so a slow model never makes another
call's lookup wait for a thread; with more simultaneous blocking model calls than that,
use an async model or pass a bigger `model_executor=`. `executor=` replaces the server
pool. To make one by hand: `AsyncVoiceSession(agent, voice=...)`, or
`AsyncVoiceSession.wrap(session)` around a `VoiceSession` you already have. An
`AsyncVoiceSession` is not a `VoiceSession`: give `.session` to code that needs one.

Python doesn't close an async stream when you `break` out of `async for`: call
`await stream.close()` after stopping early, so the model's stream is closed straight
away. An interruption (`session.cancel()`) closes it at the next piece the model sends.

### Pipecat

Wrap the LLM and TTS services you already have; nothing else in the pipeline changes:

```python
from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS   # pip install "crowkis[pipecat]"

llm = CrowkisLLM(OpenAILLMService(api_key=...))       # the cache in front of the LLM
tts = CrowkisTTS(CartesiaTTSService(voice_id=...))    # optional: replays cached audio

pipeline = Pipeline([transport.input(), stt, user_aggregator, llm, tts,
                     transport.output(), assistant_aggregator])
```

- A question the cache can answer is spoken without the LLM, and with `CrowkisTTS`,
  without the TTS either (the cached audio is played). Otherwise the LLM answers as before
  and its answer, and audio, are cached when they are safe to share.
- `CrowkisLLM` makes a `crowkis.voice_session()` (server settings from the environment,
  live-call defaults). Pass `session=` to use your own, or session options
  (`serve_above=`, `fillers=`, ...) to change them. `on_turn=` / `on_answer=` report each turn.
- `CrowkisTTS` takes the voice id and sample rate from the TTS service and finds the
  `CrowkisLLM` ahead of it by itself (or pass `llm=`).
- The model reads your system prompt (the system messages before the conversation, and
  the service's own `system_instruction`) and keeps your tools. Keep caller details out of
  the system prompt (use `session.set_values(...)`): an answer that repeats a caller detail
  found there ("Hi Asha! ...") is kept to that call and never shared. Crowkis finds such
  details by comparing an agent's system prompts across calls (what changes from caller to
  caller is theirs) and, before it has seen two, by the sentences about a person. The
  `on_turn` / `on_answer` reports show the messages the model read, system prompt included.
- `CrowkisLLM` passes the LLM service's own calls on (`llm.register_function(...)`); for its
  events use `llm.service.event_handler(...)`. When the session has no voice of its own,
  `CrowkisTTS` sets it to the TTS service's voice (and follows a change of voice).

The three processors they are made of, `crowkis_processors(session, sample_rate=...)`, still
work on their own.

### LiveKit Agents

Add `CrowkisVoice` before `Agent` in your agent class:

```python
from livekit.agents import Agent
from crowkis.integrations.livekit import CrowkisVoice   # pip install "crowkis[livekit]"

class Assistant(CrowkisVoice, Agent):
    def __init__(self):
        super().__init__(instructions="You are Acme's phone assistant.")
```

- A question the cache can answer is spoken without the LLM, and with its cached audio,
  without the TTS. Otherwise the LLM answers through LiveKit's own `llm_node`, reading your
  instructions and only the caller's question (the whole call for a personal turn), with
  your tools; the answer and its audio are cached when they are safe to share.
- A reply LiveKit cancels because the caller interrupted is never saved; an answer built
  from a tool's result stays in that call; an answer repeating a caller detail from your
  instructions ("Hi Asha! ...") is never shared.
- Each agent (one per call) makes its own `crowkis.async_voice_session()` (server settings
  from the environment). Pass `crowkis=` to use your own session, or set
  `crowkis_options = {...}` on the class for `async_voice_session()`'s options. The voice id
  and sample rate come from the session's TTS.
- If you override `llm_node` / `tts_node` yourself, call `super()` to keep Crowkis in the path.

### Bolna

Register Crowkis once when your Bolna app starts, then name it in the agent:

```python
from crowkis.integrations.bolna import register_crowkis   # pip install crowkis bolna

register_crowkis()    # adds the LLM provider "crowkis", in front of Bolna's "openai"
```

```json
"llm_config": {"provider": "crowkis", "model": "gpt-4o-mini"}
```

Bolna 0.10 pins packages that need Python 3.10 to 3.12.

- A question the cache can answer is streamed to Bolna's speech side without the LLM.
  Otherwise Bolna's own LLM answers, reading your system prompt and only the caller's
  question (the whole call for a personal turn), and the answer is cached when it is safe
  to share.
- `register_crowkis(name="crowkis-azure", base="azure")` puts Crowkis in front of another
  Bolna LLM provider. `session_options={...}` takes `async_voice_session()`'s options;
  `session_factory=` makes each call's session yourself (not both).
- Add `synthesizer="elevenlabs"` (any Bolna synthesizer key) to cache voice clips as well:
  a cached answer plays its stored clip instead of calling the TTS. Clips are kept for raw
  mu-law and PCM output only, per voice and format, and a reply cut off by a barge-in keeps none.
- Never cached: a turn with anything personal in it, and every turn after the caller told
  the call something about themselves; tool calls and their follow-ups; speculative (eager)
  turns; keypad and language-switch turns; silence nudges; JSON requests; graph,
  knowledge-base and multi-agent tasks; an answer that repeats a caller detail from your
  system prompt.
- An answer is saved only once Bolna has written it to its history in full, so a reply a
  barge-in trimmed or dropped is never saved. It is saved when the next turn starts, or when
  the call ends.
- Each call gets its own session, so no caller's details are shared. A Crowkis failure never
  breaks a call: Bolna's LLM answers instead. `llm.failures` (a `Counter`, also on the
  synthesizer) counts each failed step by name.

### Calling your model yourself

`answer()` calls your model for you. When you need to call it yourself (to stream it to your
TTS, use your own retries, or run it inside a framework), split the turn in three:

```python
decision = session.decide(caller_said)
if decision.needs_model:
    # None means a personal turn: the model reads the whole call.
    messages = decision.messages or session.injections() + [{"role": "user", "content": caller_said}]
    reply = my_model(messages)
    session.record(decision, reply)            # same rules as answer()
speak(decision.text)
```

`decision.messages` is what the model may read: the question alone (or with the questions it
follows on from) when the answer may be shared, or `None` when the turn is personal, and then
give the model the whole call (`session.injections()` plus the question). `record()` then
saves the answer under exactly the same rules as `answer()`, and fills in `decision.text`,
`stored`, `not_stored` and `empty`. If your model read a system prompt, pass it too (`record(decision, reply, system=...)`, and `system=` to `answer()` and `respond()`): an answer that repeats a detail it gives about this caller (a name, an account number) is kept to the call. Better still, keep caller details out of the system prompt and use `set_values()`. Pass `private=True` for an answer that must stay in this
call even though the question was general, such as one built from a tool's result.

`record()` raises `ValueError` for a decision from another session, a turn served from the
cache or a filler, or a turn already recorded. It never raises because the server refused
the write: that is reported in `decision.not_stored`. If the caller talks over the answer,
call `session.cancel()`; a later `record()` for that turn then stores nothing. Each call
needs its own session: decisions can't be recorded in another call's session.

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
admin = CrowkisAdmin("http://127.0.0.1:6384", token=token)   # the dashboard / management port
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
