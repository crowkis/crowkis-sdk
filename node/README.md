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

```ts
import { Agent, VoiceSession } from "@crowkis/client";

const agent = new Agent("support-line", { tenant: "my-app" });
const session = new VoiceSession(agent, { voice: "my-voice" });

// myModel(messages) resolves to a string. It is called only when the cache cannot
// answer, with exactly the messages Crowkis chose, and its answer is cached when
// it is safe to share.
const decision = await session.answer(callerSaid, myModel);
speak(decision.text);
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

If your server sets an auth token (`CROWKIS_AUTH_TOKEN`), pass it from your environment —
never hard-code it. Keep it in a gitignored `.env`.

```ts
const cache = new Crowkis({
  host: process.env.CROWKIS_HOST ?? "127.0.0.1",
  port: Number(process.env.CROWKIS_PORT ?? 6383),
  tenant: "my-app",
  authToken: process.env.CROWKIS_TOKEN,   // from .env, not the code
});
```

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
