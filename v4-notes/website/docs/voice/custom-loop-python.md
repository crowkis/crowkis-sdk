---
title: Custom voice loop (Python)
path: /docs/voice/custom-loop-python
sdk_version: 0.5.2
---

# Crowkis in your own voice loop (Python)

*Crowkis SDK 0.5.2 · Python 3.9+*

For a bot you wrote yourself, for example Twilio audio → Deepgram STT → OpenAI → ElevenLabs TTS.

## Add it

```bash
pip install crowkis
```

Make one session per phone call, and ask it first for each thing the caller says:

```python
session = crowkis.async_voice_session()
stream = await session.respond(caller_said, my_streaming_llm, system=SYSTEM)
async for piece in stream: await tts.send(piece)
```

Your LLM is called only when the cache can't answer. Its streamed answer is saved when the stream ends, if it's safe to share.

## The whole loop

`SYSTEM`, `my_streaming_llm`, `tts`, `play` and `caller_interrupted` are yours: your system prompt, LLM, TTS, audio player and barge-in check. `caller_turns` is any async iterable of transcripts.

```python
import crowkis

async def run_call(caller_turns):                     # your STT's final transcripts
    session = crowkis.async_voice_session()            # one per call
    try:
        async for said in caller_turns:
            stream = await session.respond(said, my_streaming_llm, system=SYSTEM)
            if stream.decision.audio:                  # a cached answer with its audio
                await play(stream.decision.audio)      # no TTS
                await stream.close()
                continue
            async for piece in stream:                 # cached text, or the LLM's words as they arrive
                if caller_interrupted():
                    session.cancel()                   # stops the LLM; nothing is saved
                    break
                await tts.send(piece)
            await stream.close()
    finally:
        await session.close()
```

`my_streaming_llm(messages)` returns the LLM's text pieces: an async or plain iterable, or a whole `str`. With the OpenAI SDK:

```python
from openai import AsyncOpenAI

openai = AsyncOpenAI()

async def my_streaming_llm(messages):
    chunks = await openai.chat.completions.create(model="gpt-4o-mini", messages=messages, stream=True)
    async for chunk in chunks:
        if chunk.choices:
            yield chunk.choices[0].delta.content
```

There's no asyncio in your app? `crowkis.voice_session()` gives the same API without `await`. Close it at the end of the call with `session.agent.close()`.

## Connect to your server

```bash
# .env
CROWKIS_HOST=10.0.0.5
CROWKIS_PORT=6383
CROWKIS_AUTH_TOKEN=change-me
CROWKIS_TENANT=my-app
```

Load it with `python-dotenv` (`from dotenv import load_dotenv; load_dotenv()`) or set the variables in your shell: the SDK doesn't read `.env` itself. With nothing set, it connects to `127.0.0.1:6383` with no token.

To cache audio too, pass your TTS voice id and a synthesiser: `async_voice_session(voice="eleven-rachel", synthesise=my_tts)`, where `my_tts(text) -> bytes` is a plain (not async) function. A hit then comes with `decision.audio`.

## Try it without API keys

A stand-in LLM that counts its calls, and the same question asked twice:

```python
import asyncio
import crowkis

calls = 0

async def fake_llm(messages):
    global calls
    calls += 1
    for piece in ["The museum opens ", "at ten on weekdays."]:
        yield piece

async def main():
    session = crowkis.async_voice_session()
    try:
        for said in ["What time does the city museum open on weekdays?"] * 2:
            stream = await session.respond(said, fake_llm)
            print(stream.decision.action, "|", "".join([p async for p in stream]))
            await stream.close()
        print("LLM calls:", calls, session.stats()["served_from_cache"])
    finally:
        await session.close()

asyncio.run(main())
# infer | The museum opens at ten on weekdays.
# serve | The museum opens at ten on weekdays.
# LLM calls: 1 1
```

## Check it's working

```python
print(session.stats())
# {'turns': 5, 'served_from_cache': 3, 'model_calls': 2, 'cache_hit_pct': 60.0, ...}
```

Each turn also says what happened: `stream.decision.action` (`"serve"`, `"infer"` or `"filler"`), `decision.reason`, and after the stream ends, `decision.stored` and `decision.not_stored`.

## When things go wrong

- **Server down or slow:** `respond()` waits at most 250 ms, then calls your LLM. Saving the answer waits at most 500 ms, then finishes in the background (`decision.not_stored` then says so).
- **The LLM fails mid-stream:** the error is raised and nothing is saved.
- **The caller interrupts:** call `session.cancel()`. The stream stops at the next piece and closes your LLM's stream, so no more tokens are billed. Nothing is saved.
- **Leaving the loop early:** call `await stream.close()`. Python doesn't close an async stream for you on `break`.
- **Audio cache error, or your synthesiser fails:** `decision.audio` is `None`. Speak the text with your TTS.
- **One session per call.** Never share a session between callers.
