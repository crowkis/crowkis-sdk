---
title: Custom voice loop (Node.js)
path: /docs/voice/custom-loop-node
sdk_version: 0.5.2
---

# Crowkis in your own voice loop (Node.js)

*Crowkis SDK 0.5.2 · Node.js 18+*

For a bot you wrote yourself, for example a Twilio media stream → Deepgram → OpenAI → ElevenLabs.

## Add it

```bash
npm install @crowkis/client
```

Make one session per phone call, and ask it first for each thing the caller says:

```js
const session = voiceSession();
const stream = await session.respond(callerSaid, myStreamingLlm, { system: SYSTEM });
for await (const piece of stream) await tts.send(piece);
```

Your LLM is called only when the cache can't answer. Its streamed answer is saved when the stream ends, if it's safe to share.

## The whole loop

`SYSTEM`, `myStreamingLlm`, `tts`, `play` and `callerInterrupted` are yours: your system prompt, LLM, TTS, audio player and barge-in check. `callerTurns` is any iterable or async iterable of transcripts (an array works).

```js
const { voiceSession } = require("@crowkis/client");   // or: import { voiceSession } from "@crowkis/client"

async function runCall(callerTurns) {                  // your STT's final transcripts
  const session = voiceSession();                      // one per call
  try {
    for await (const said of callerTurns) {
      const stream = await session.respond(said, myStreamingLlm, { system: SYSTEM });
      if (stream.decision.audio) {                     // a cached answer with its audio
        await play(stream.decision.audio);             // no TTS
        continue;
      }
      for await (const piece of stream) {              // cached text, or the LLM's words as they arrive
        if (callerInterrupted()) {
          session.cancel();                            // stops the LLM; nothing is saved
          break;
        }
        await tts.send(piece);
      }
    }
  } finally {
    await session.agent.close();
  }
}
```

`myStreamingLlm(messages)` returns the LLM's text pieces: an async iterable, or a whole string. With the OpenAI SDK:

```js
const OpenAI = require("openai");
const openai = new OpenAI();

async function* myStreamingLlm(messages) {
  const chunks = await openai.chat.completions.create({ model: "gpt-4o-mini", messages, stream: true });
  for await (const chunk of chunks) yield chunk.choices[0]?.delta?.content;
}
```

## Connect to your server

```bash
# .env  (load it with dotenv, or run: node --env-file=.env bot.js on Node 20.6+)
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

On Node 18, load it with `dotenv` (`require("dotenv").config()` at the top). The SDK doesn't read `.env` itself. With nothing set, it connects to `127.0.0.1:6383` with no token.

To cache audio too, pass your TTS voice id and a synthesiser: `voiceSession({ voice: "eleven-rachel", synthesise: myTts })`. A hit then comes with `decision.audio`.

## Try it without API keys

A stand-in LLM that counts its calls, and the same question asked twice:

```js
const { voiceSession } = require("@crowkis/client");

let calls = 0;
async function* fakeLlm() {
  calls += 1;
  for (const piece of ["The museum opens ", "at ten on weekdays."]) yield piece;
}

async function main() {
  const session = voiceSession();
  try {
    for (const said of Array(2).fill("What time does the city museum open on weekdays?")) {
      const stream = await session.respond(said, fakeLlm);
      let text = "";
      for await (const piece of stream) text += piece;
      console.log(stream.decision.action, "|", text);
    }
    console.log("LLM calls:", calls, session.stats().servedFromCache);
  } finally {
    await session.agent.close();
  }
}
main();
// infer | The museum opens at ten on weekdays.
// serve | The museum opens at ten on weekdays.
// LLM calls: 1 1
```

## Check it's working

```js
console.log(session.stats());
// { turns: 5, servedFromCache: 3, modelCalls: 2, cacheHitPct: 60, ... }
```

Each turn also says what happened: `stream.decision.action` (`"serve"`, `"infer"` or `"filler"`), `decision.reason`, and after the stream ends, `decision.stored` and `decision.notStored`.

## When things go wrong

- **Server down or slow:** `respond()` waits at most 250 ms, then calls your LLM. Saving the answer waits at most 500 ms, then finishes in the background (`decision.notStored` then says so).
- **The LLM fails mid-stream:** the error is thrown and nothing is saved.
- **The caller interrupts:** call `session.cancel()`. The stream stops at the next piece and closes your LLM's stream. Nothing is saved.
- **Audio cache error, or your synthesiser fails:** `decision.audio` is empty. Speak the text with your TTS.
- **One session per call.** Never share a session between callers.
