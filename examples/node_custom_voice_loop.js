"use strict";
// A hand-written voice loop with Crowkis: speech-to-text -> streaming LLM -> TTS.
//
//   npm install @crowkis/client openai
//   # .env: CROWKIS_HOST / CROWKIS_PORT / CROWKIS_AUTH_TOKEN (see the README)
//   node --env-file=.env examples/node_custom_voice_loop.js   # runs with stand-ins
//
// runCall() is the part that matters: for each thing the caller says it asks Crowkis
// first (respond), plays cached audio when Crowkis has it, otherwise streams the LLM's
// words into your TTS, and stops (cancel) when the caller talks over the answer. In a
// phone bot, callerTurns is Deepgram's final transcripts from a Twilio media stream,
// speakText sends text to ElevenLabs, and playAudio writes μ-law/PCM back to Twilio.

const { voiceSession } = require(process.env.CROWKIS_SDK || "@crowkis/client");

const SYSTEM = "You are Acme's phone assistant. Be brief and friendly.";

async function runCall(session, callerTurns, llm, speakText, playAudio, bargedIn = () => false) {
  const spoken = [];
  for await (const said of callerTurns) {
    const stream = await session.respond(said, llm, { system: SYSTEM });
    if (stream.decision.audio) {
      await playAudio(stream.decision.audio); // a cached answer with its audio: no TTS
      spoken.push(stream.decision.text);
      continue;
    }
    const parts = [];
    for await (const piece of stream) {
      // cached text, or the LLM's words as they arrive
      if (bargedIn()) {
        session.cancel(); // stops the LLM and saves nothing
        break;
      }
      await speakText(piece);
      parts.push(piece);
    }
    spoken.push(parts.join(""));
  }
  return spoken;
}

// -- stand-ins: replace them with your real services ------------------------------------

// The real one, with the OpenAI SDK:
//   const chunks = await openai.chat.completions.create({ model: "gpt-4o-mini", messages, stream: true });
//   for await (const chunk of chunks) yield chunk.choices[0]?.delta?.content;
async function* openaiLlm() {
  for (const word of "Refunds take five business days to reach your card.".split(" ")) {
    await new Promise((r) => setTimeout(r, 10));
    yield `${word} `;
  }
}

async function* caller(lines) {
  for (const line of lines) yield line; // the real one: Deepgram's final transcripts
}

const ttsSend = async (text) => console.log("  tts <-", text); // the real one: ElevenLabs websocket
const play = async (audio) => console.log(`  playing ${audio.length} bytes of cached audio`);

async function main(session = voiceSession()) {
  try {
    return await runCall(session, caller(["what is your refund policy", "what is your refund policy"]), openaiLlm, ttsSend, play);
  } finally {
    await session.agent.close();
  }
}

module.exports = { runCall, main };

if (require.main === module) {
  main().then((lines) => lines.forEach((line) => console.log("bot:", line)));
}
