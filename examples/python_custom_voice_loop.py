"""A hand-written voice loop with Crowkis: speech-to-text -> streaming LLM -> TTS.

    pip install crowkis openai
    # .env: CROWKIS_HOST / CROWKIS_PORT / CROWKIS_AUTH_TOKEN (see the README)
    python examples/python_custom_voice_loop.py      # runs with stand-in STT / LLM / TTS

run_call() is the part that matters: for each thing the caller says it asks Crowkis
first (respond), plays cached audio when Crowkis has it, otherwise streams the LLM's
words into your TTS, and stops (cancel) when the caller talks over the answer. Swap the
stand-ins below for your real services; nothing in run_call() changes.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterable, Awaitable, Callable, List, Optional

import crowkis

SYSTEM = "You are Acme's phone assistant. Be brief and friendly."


async def run_call(
    session: "crowkis.AsyncVoiceSession",
    caller_turns: AsyncIterable[str],
    llm: Callable,
    speak_text: Callable[[str], Awaitable[None]],
    play_audio: Callable[[bytes], Awaitable[None]],
    barged_in: Callable[[], bool] = lambda: False,
) -> List[str]:
    """One call. ``caller_turns`` yields what the caller says (your STT's final
    transcripts); ``llm(messages)`` streams the model's text; ``speak_text`` sends a piece
    of text to your TTS; ``play_audio`` plays cached audio; ``barged_in()`` says whether
    the caller started talking over the answer. Returns what was said, turn by turn."""
    spoken: List[str] = []
    async for said in caller_turns:
        stream = await session.respond(said, llm, system=SYSTEM)
        if stream.decision.audio:
            await play_audio(stream.decision.audio)  # a cached answer with its audio: no TTS
            spoken.append(stream.decision.text)
            continue
        parts = []
        async for piece in stream:  # cached text, or the LLM's words as they arrive
            if barged_in():
                session.cancel()  # stops the LLM and saves nothing
                break
            await speak_text(piece)
            parts.append(piece)
        await stream.close()
        spoken.append("".join(parts))
    return spoken


# -- stand-ins: replace them with your real services ------------------------------------

async def openai_llm(messages):
    """The real one, with the OpenAI SDK (any OpenAI-compatible endpoint works):

        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        stream = await client.chat.completions.create(model="gpt-4o-mini", messages=messages, stream=True)
        async for chunk in stream:
            if chunk.choices:
                yield chunk.choices[0].delta.content
    """
    for word in "Refunds take five business days to reach your card.".split(" "):
        await asyncio.sleep(0.01)
        yield word + " "


async def caller(lines):
    """The real one: your STT's final transcripts (Deepgram, Whisper, ...)."""
    for line in lines:
        yield line


async def tts_send(text: str) -> None:
    """The real one: send the text to your streaming TTS (ElevenLabs, Cartesia, ...)."""
    print("  tts <-", text)


async def play(audio: bytes) -> None:
    """The real one: write the cached audio to your call's output."""
    print(f"  playing {len(audio)} bytes of cached audio")


async def main(session: Optional["crowkis.AsyncVoiceSession"] = None) -> List[str]:
    session = session or crowkis.async_voice_session()
    try:
        return await run_call(session, caller(["what is your refund policy", "what is your refund policy"]),
                              openai_llm, tts_send, play)
    finally:
        await session.close()


if __name__ == "__main__":
    for line in asyncio.run(main()):
        print("bot:", line)
