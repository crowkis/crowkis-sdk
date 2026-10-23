---
title: LiveKit Agents (Node.js)
path: /docs/voice/livekit-node
sdk_version: 0.5.2
---

# Crowkis in a LiveKit agent (Node.js)

*Crowkis SDK 0.5.2 (Node.js 18+) · @livekit/agents 1.9 (tested on 1.9.3)*

## Add it

```bash
npm install @crowkis/client @livekit/agents@1.9.3
```

Wrap your agent (CommonJS shown; with ES modules, `import { withCrowkis } from "@crowkis/client/livekit"` works the same):

```js
const { voice } = require("@livekit/agents");
const { withCrowkis } = require("@crowkis/client/livekit");
const agent = withCrowkis(new voice.Agent({ instructions: "You are Acme's phone assistant." }));
```

Your STT, LLM and TTS plugins and your `AgentSession` stay exactly as they are.

## Connect to your server

```bash
# .env  (load it with dotenv, or run: node --env-file=.env agent.js on Node 20.6+)
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

`withCrowkis` builds a `voiceSession()` from these on the first turn, with live-call defaults. Use one wrapped agent per call. To set options, pass `withCrowkis(agent, { options: { serveAbove: 0.95 } })`. To use your own session, pass `withCrowkis(agent, { crowkis: voiceSession({...}) })`.

## What happens on each turn

| The caller asks… | What Crowkis does |
|---|---|
| Something already answered | Speaks the cached answer without the LLM, and with its cached audio, without the TTS. |
| Something new | Your LLM answers through the agent's own `llmNode`, reading your instructions and the caller's question, with your tools. The answer is saved once the TTS has spoken it, when it's safe to share. |
| Something personal | The LLM reads the whole call. Nothing is saved. |
| They interrupt | The answer is cut off, so nothing is saved, and the LLM stream is stopped at once. |

## Check it's working

```js
// at the end of the call:
console.log(agent.crowkis.stats());
// { turns: 6, servedFromCache: 3, modelCalls: 3, cacheHitPct: 50, ... }
```

## Try it without a room or API keys

On a miss, the wrapped agent calls the agent's own `llmNode(chatCtx, toolCtx, modelSettings)`. So a subclass with a stand-in `llmNode` is enough to try it. With no `AgentSession` (no audio output), an answer is saved as soon as its stream ends:

```js
const { voice, llm } = require("@livekit/agents");
const { withCrowkis } = require("@crowkis/client/livekit");

let calls = 0;
class MyAgent extends voice.Agent {
  async llmNode() {
    calls += 1;
    return new ReadableStream({ start(c) { c.enqueue("We open at ten on weekdays."); c.close(); } });
  }
}
const agent = withCrowkis(new MyAgent({ instructions: "You are Acme's phone assistant." }));

async function ask(question) {
  const ctx = llm.ChatContext.empty();
  ctx.addMessage({ role: "user", content: question });
  let text = "";
  for await (const chunk of await agent.llmNode(ctx, {}, {})) text += typeof chunk === "string" ? chunk : chunk.delta?.content ?? "";
  return text;
}

(async () => {
  for (let i = 0; i < 2; i += 1) console.log(await ask("What time does the city museum open on weekdays?"));
  console.log("LLM calls:", calls, agent.crowkis.stats().servedFromCache);   // LLM calls: 1 1
  await agent.crowkis.agent.close();   // close the session's connection, so the script exits
})();
```

`agent.crowkis` is the wrapped agent's voice session, and `agent.crowkis.agent` its connection to Crowkis. Passing `{}` for `toolCtx` and `modelSettings` is fine when you call `llmNode` yourself.

## When things go wrong

- **Server down or slow:** the turn goes to your LLM after at most 250 ms, and saving waits at most 500 ms. See `cacheUnavailable`, `missedLatencyBudget` and `slowWrites`.
- **Audio cache error:** the text is still spoken (`audioUnavailable`).
- **Audio output turned off:** answers are saved as soon as they are written, since nothing will speak them.
- **Instructions with caller details:** an answer that repeats them is never shared.
- **Earlier messages in the chat context:** Crowkis reads them too. A caller line that tells the call something keeps the rest of the call private.
