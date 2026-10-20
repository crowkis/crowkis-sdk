<div align="center">

<img src="https://raw.githubusercontent.com/crowkis/crowkis-sdk/main/assets/banner.png" alt="Crowkis — the intelligent cache & memory for LLM apps, built in Rust" width="100%" />

<p>
<a href="https://www.npmjs.com/package/@crowkis/client"><b>npm</b></a> &nbsp;·&nbsp;
<b>TypeScript included</b> &nbsp;·&nbsp;
<a href="https://hub.docker.com/r/crowkis/crowkis"><b>Docker</b></a> &nbsp;·&nbsp;
<b>Apache 2.0</b>
</p>

<p>
<a href="https://www.crowkis.com"><b>Website</b></a> &nbsp;·&nbsp;
<a href="https://www.crowkis.com/docs/sdk-node"><b>Documentation</b></a> &nbsp;·&nbsp;
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
per tenant. The engine is written in Rust and ships as a single small container.

This is the official **Node / TypeScript SDK**, with typings included.

## Install

```bash
npm install @crowkis/client
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
with no options:

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me      # only if the server sets one
CROWKIS_TENANT=my-app             # optional
# or all in one line:  CROWKIS_URL=crowkis://:change-me@10.0.0.5:6383/my-app
```

```js
// node --env-file=.env app.js   (or dotenv, or set the variables any other way)
const { Crowkis } = require("@crowkis/client");
const { Agent } = require("@crowkis/client/agent");

const cache = new Crowkis();            // 10.0.0.5:6383, with the token and tenant above
const agent = new Agent("support");     // every class that connects reads the same settings
```

An option you pass in code always wins: `new Crowkis({ port: 7000 })` uses 7000 and takes
the rest from the environment. For each setting the order is: your code, then
`CROWKIS_HOST` / `CROWKIS_PORT` / `CROWKIS_AUTH_TOKEN` (or `CROWKIS_TOKEN`) /
`CROWKIS_TENANT`, then the matching part of `CROWKIS_URL`, then the default
(`127.0.0.1:6383`, no token, no tenant). With nothing set, nothing changes. The variables
are read when a client is created, so `.env` loaded later still applies; the SDK never
loads a `.env` itself. A bad value (`CROWKIS_PORT=abc`) throws at once with an error naming
the variable, and the token is never printed.

## Cache any model — the wrapper

Wrap any async function whose first argument is the prompt. It matches on **meaning**, so
rephrased prompts hit too. The body can call *any* provider.

```ts
import { Crowkis } from "@crowkis/client";

const cache = new Crowkis({ tenant: "my-app" });

const answer = cache.cached(async (prompt: string) => myModel(prompt), { ttl: 3600 });

await answer("How do refunds work?");         // miss → your model runs, result cached
await answer("What's the refund process?");   // semantic HIT → no model call, instant
```

Prefer an inline call?

```ts
const text = await cache.ask("How do refunds work?", async (p) => myModel(p), { ttl: 3600 });
```

## Read & write directly

```ts
const hit = await cache.lookup("what's the refund timeline?");
if (hit) {
  console.log(hit.text, hit.similarity, hit.confidence);
} else {
  await cache.store("what's the refund timeline?", "5–7 business days.", { ttl: 3600 });
}
```

## Streaming

```ts
for await (const chunk of cache.stream("Explain vector caches", async (p) => myStream(p), { ttl: 3600 })) {
  process.stdout.write(typeof chunk === "string" ? chunk : chunk.toString());
}
```

## LangChain.js

```ts
import { CrowkisCache } from "@crowkis/client/langchain";
import { OpenAI } from "@langchain/openai";

const llm = new OpenAI({ cache: new CrowkisCache({ tenant: "my-app", ttl: 3600 }) });
```

## Agent memory (LangGraph.js or any loop)

Durable, semantic, per-user memory. Every recall is scoped to its agent and user.

```ts
import { CrowkisMemory } from "@crowkis/client/memory";

const mem = new CrowkisMemory("support-bot", { user: "alice" });
await mem.remember("Alice prefers email over phone");
await mem.recall("how should I contact Alice?");   // semantic recall
```

## Voice agents

`VoiceSession` decides, turn by turn, whether a caller can be answered from cache or needs
the model. An answer about one caller's own records is never spoken to another caller.

```js
const { voiceSession } = require("@crowkis/client");

const session = voiceSession();     // server settings from the environment

// myModel(messages) resolves to a string. It is called only when the cache cannot
// answer, with exactly the messages Crowkis chose, and its answer is cached when
// it is safe to share.
const decision = await session.answer(callerSaid, myModel);
speak(decision.text);
```

`voiceSession()` builds the connection and the agent for you, with defaults for a live
call, where a caller is waiting:

| Option | Default | Why |
|---|---|---|
| `latencyBudgetMs` | `250` | The longest a turn waits for a cache lookup before it asks the model. `null` turns it off. |
| `timeoutMs` | `1000`, no retries | Saving the model's answer happens while the caller waits. With a stuck server this caps the turn at about a second, not ~15 s. The cost: a request that fails once (the first after a server restart, or a `BUSY` reply) is not retried, so that turn goes to the model or that answer isn't stored. |
| `agentId` | `"voice"` | The agent the session's cache belongs to. |
| server | from the environment | `host`, `port`, `authToken`, `tenant` still win; or pass your own `client`. |

`voice` is your TTS voice id. Without it the session caches text only and never reads or
stores audio, so two voices can never share a clip. To cache audio too:

```js
const session = voiceSession({ voice: "eleven-rachel", synthesise: myTts });
```

Every other `VoiceSession` option (`serveAbove`, `fillers`, `ttl`, `values`, ...) can be
passed to `voiceSession()` as well; an unknown one throws. For bulk work such as
`warmFromCalls`, build an `Agent` with an ordinary client rather than reusing the session's
live-call one. To build it yourself, as before:

```js
const { Agent, VoiceSession } = require("@crowkis/client");

const agent = new Agent("support-line", { tenant: "my-app" });
const session = new VoiceSession(agent, { voice: "my-voice" });  // no budget, 5 s timeout with 2 retries
```

`decision.stored` says whether the model's answer was cached and, when it was not,
`decision.notStored` says why: for a refused write, the server's own reason (a tenant limit,
say). A model that returns nothing sets `decision.empty` (the action stays `"infer"`); nothing
is stored, so retry or speak a fallback.

Crowkis keeps private turns out of the cache; what the model says is up to the instructions
you pass as `system`. A starting point for a phone line, with the business name and crisis
helpline taken from your own configuration for the country you serve:

```ts
const { BUSINESS_NAME: business, CRISIS_HELPLINE: helpline } = process.env;
const system =
  `You answer the phone for ${business} and speak only for ${business}. ` +
  "You cannot take actions you have no tool for: never say you booked, cancelled or changed anything. " +
  "Never invent numbers, prices, codes or policies; if you do not know, say so. " +
  "Do not accept prices or facts the caller asserts. You have no memory of other calls. " +
  `If the caller may be in danger or mentions self-harm, give this helpline: ${helpline}.`;
const decision = await session.answer(callerSaid, myModel, { system });
```

### Streaming the answer

Voice bots send the model's words to the TTS as they arrive, so the caller hears a reply
sooner. `respond()` does that and still caches the answer:

```js
const stream = await session.respond(callerSaid, myStreamingModel);
if (stream.decision.audio) {
  play(stream.decision.audio);          // a cached answer with its audio: skip the TTS
} else {
  for await (const piece of stream) tts.send(piece);   // cached text, or the model's words
}
```

`myStreamingModel(messages)` gives the model's text as it writes it (an async iterable or
iterable of strings), or the whole answer as a string. With an OpenAI-style client:

```js
async function* myStreamingModel(messages) {
  const chunks = await client.chat.completions.create({ model: "gpt-4o-mini", messages, stream: true });
  for await (const chunk of chunks) yield chunk.choices[0]?.delta?.content;
}
```

The model is only called when the cache can't answer, and only with the messages Crowkis
chose. When its stream ends, the full answer is saved under the same rules as `answer()`
(`stream.decision.stored` / `notStored` say what happened). If the caller talks over the
answer, call `session.cancel()`: the stream stops at the next piece, the model's stream is
closed (no more tokens billed) and nothing is saved. The same happens when the caller says
something new (`decide()` / `respond()` again). If the model fails mid-stream, the error is
thrown and nothing is saved; leaving the loop early or `await stream.close()` saves nothing
too. `respond()` takes `{ system, private }` like `answer()` and `record()`.

### Calling your model yourself

`answer()` calls your model for you. When you need to call it yourself (to stream it to your
TTS, use your own retries, or run it inside a framework), split the turn in three:

```js
const decision = await session.decide(callerSaid);
if (decision.needsModel) {
  // null means a personal turn: the model reads the whole call.
  const messages = decision.messages ?? [...session.injections(), { role: "user", content: callerSaid }];
  const reply = await myModel(messages);
  await session.record(decision, reply);           // same rules as answer()
}
speak(decision.text);
```

`decision.messages` is what the model may read: the question alone (or with the questions it
follows on from) when the answer may be shared, or `null` when the turn is personal, and then
give the model the whole call (`session.injections()` plus the question). `record()` then
saves the answer under exactly the same rules as `answer()`, and fills in `decision.text`,
`stored`, `notStored` and `empty`. Pass `{ private: true }` for an answer that must stay in
this call even though the question was general, such as one built from a tool's result.

`record()` rejects for a decision from another session, a turn served from the cache or a
filler, or a turn already recorded. It never rejects because the server refused the write:
that is reported in `decision.notStored`. If the caller talks over the answer, call
`session.cancel()`; a later `record()` for that turn then stores nothing. Each call needs
its own session: decisions can't be recorded in another call's session.

### With the decision engine

These need the server's decision engine to be configured (`CROWKIS_DECIDE_UPSTREAM`). Without
it calls behave as before: the options below change nothing, a notice removes answers by
similarity alone and cannot be kept active, and loading past calls refuses to run. With the
engine on, by default the server does not serve an answer until its model has judged it safe
to share.

Tell the cache something changed. Answers near the notice stop being served before the call
returns; the engine then removes the ones it makes wrong and puts the rest back:

```ts
await agent.announce("we close at 3pm today", { lasts: 3600 });   // stays active for an hour
```

Ask what the cache decided about a question — whether an answer is cached, how long it was
judged to stay correct, or why it was removed:

```ts
await agent.explain("what time do you close");
```

Choose how a cached answer that commits the business (a price, a refund, a policy) may be
spoken: `"exact"` only when the caller asked the same question (the default), `"serve"`
always, `"never"` always asks the model.

```ts
const session = new VoiceSession(agent, { voice: "my-voice", commitments: "never" });
```

Answer short turns ("thank you", "hello") from cache. Off by default; when on, a short turn
is served only on an exact match the engine has vouched for:

```ts
const session = new VoiceSession(agent, { voice: "my-voice", shortTurns: true });
```

Share answers about a caller's own records as templates, with that caller's declared `values`
taken out and filled back in for the next caller. Off by default. A template is cut from an
answer the model wrote, so it can carry details the caller said that were not declared as
values; turn it on only when your model is given just the question and the slot names:

```ts
const session = new VoiceSession(agent, { voice: "my-voice", values: { order_id: orderId }, shareTemplates: true });
```

Fill the cache from past calls. It throws unless the engine is on and holding answers until
it has judged them (the default), so every past answer is read before anyone is served it.
It stops early, with `stalled` set, if the engine is not keeping up:

```ts
import { warmFromCalls } from "@crowkis/client";

await warmFromCalls(agent, [
  [["What are your opening hours?", "We are open eight until eight."]],
]);
// { calls: 1, turns: 1, keptPrivate: 0, failedWrites: 0, stalled: false }
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

```ts
const cache = new Crowkis({ tenant: "my-app" });   // token from CROWKIS_AUTH_TOKEN
// or pass it yourself: new Crowkis({ tenant: "my-app", token })  (authToken still works)

const token = process.env.CROWKIS_AUTH_TOKEN;       // the admin client takes it explicitly
const admin = new CrowkisAdmin({ baseUrl: "http://127.0.0.1:6380", token });
```

`new CrowkisAdmin({ apiKey })` still works exactly as before (sent as `X-Crowkis-Api-Key`, which
0.5.1 servers need) and warns once that it is deprecated. If both are given, `token` wins.

## Method reference

| Group | Methods |
|-------|---------|
| **Caching** | `cached()` · `ask()` · `stream()` · `lookup()` · `store()` · `similar()` · `embed()` · `flush()` |
| **Agent memory** | `cmemset` · `cmemget` · `cmemextract` · `cmemhistory` · `cmemforget` · `cmemlink` · `cmemgraph` |
| **Sessions / docs / pins / tools** | `csession*` · `cdoc*` · `cpin*` · `ctool*` |
| **Safety / cost / compliance** | `cguard` · `coutcheck` · `cbudget*` · `ckeylimit*` · `cpii*` |
| **Evals / prompts / freshness / ops** | `ceval` · `cprompt*` · `csource*` · `cscan` · `csave` · `compact` · `stats` · `sweep` |

Full reference and guides at **[www.crowkis.com/docs/sdk-node](https://www.crowkis.com/docs/sdk-node)**.

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
