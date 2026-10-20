"use strict";

// Crowkis in a LiveKit Agents (Node) agent: the Node side of
// python/crowkis/integrations/livekit.py.
//
//   const { voice } = require("@livekit/agents");
//   const { withCrowkis } = require("@crowkis/client/livekit");
//
//   const agent = withCrowkis(new voice.Agent({ instructions: "You are Acme's phone assistant." }));
//
// withCrowkis(agent, { crowkis }) wraps the agent's llmNode and ttsNode (its own, so an
// override of yours keeps working) and returns the same agent. Each agent (one per call)
// gets its own Crowkis session, made with voiceSession() (server settings from the
// environment, live-call defaults), unless you pass `crowkis`.
//
// llmNode  asks Crowkis first, on a reply to what the caller just said. A cached answer
//          is spoken without the LLM; otherwise the LLM answers, reading the agent's
//          instructions and only what Crowkis chose (the whole call for a personal turn),
//          with its tools. A reply that is not to a new caller turn (generateReply with
//          instructions, onEnter) and a turn carrying RAG / CRM messages or a running tool
//          go to the LLM unchanged, never shared. An answer built from a tool's result
//          stays in the call.
// ttsNode  plays a cached answer's audio without the TTS when Crowkis has it (matched by
//          the text being spoken, so a say() never gets another reply's clip), and saves a
//          new answer once its TTS run has spoken it. LiveKit never speaks a preemptive
//          attempt it discarded, so such an attempt is never saved; an answer cut off while
//          being spoken is not saved either. With no TTS (audio off), an answer is saved
//          when the LLM has finished it. The voice and sample rate come from the agent's TTS.
//
// Needs @livekit/agents 1.x.

const { voiceSession, _words: wordsOf } = require("./voice.js");
const { AudioClips } = require("./voiceTurns.js");

const RUNNING_PLACEHOLDER_KEY = "__lk_running_placeholder__";
const FRAME_MS = 20;

const textOf = (item) => (item && typeof item.textContent === "string" ? item.textContent : "");
const isTool = (item) => item && (item.type === "function_call" || item.type === "function_call_output");
const isConversation = (item) => item && item.type === "message" && (item.role === "user" || item.role === "assistant");

function lastUser(chatCtx) {
  const items = [...chatCtx.items];
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].type === "message" && items[i].role === "user") return [textOf(items[i]), items.slice(i + 1), i];
  }
  return [null, items, -1];
}

// The agent's instructions: the system / developer message LiveKit puts first.
function leadingInstructions(chatCtx) {
  const first = chatCtx.items[0];
  return first && first.type === "message" && (first.role === "system" || first.role === "developer") ? [first] : [];
}

// More than instructions and conversation for this turn: something right before the
// caller's last message that is not conversation (RAG or CRM data), or a running tool.
function extraContext(chatCtx, lastUserIndex) {
  const items = [...chatCtx.items];
  if (items.some((i) => i && i.extra && RUNNING_PLACEHOLDER_KEY in i.extra)) return true;
  const before = lastUserIndex - 1;
  return before >= leadingInstructions(chatCtx).length && !isConversation(items[before]);
}

function voiceOf(tts) {
  for (const holder of [tts, tts && (tts.opts || tts._opts)]) {
    if (!holder) continue;
    for (const name of ["voice", "voiceId", "voice_id", "voiceName", "speaker"]) {
      let value = holder[name];
      if (value && typeof value === "object") value = value.id;
      if (typeof value === "string" && value.trim()) return value.trim();
    }
  }
  return null;
}

const chunkText = (chunk) =>
  typeof chunk === "string" ? chunk : chunk && chunk.delta && typeof chunk.delta.content === "string" ? chunk.delta.content : "";
const chunkCallsTool = (chunk) => Boolean(chunk && chunk.delta && chunk.delta.toolCalls && chunk.delta.toolCalls.length);
// The same words, whatever LiveKit's text transforms did to markup and spacing.
const same = (a, b) => wordsOf(a).join(" ") === wordsOf(b).join(" ");

// An async iterable as a web ReadableStream that, when LiveKit cancels it, stops the
// iterable (its finally blocks run) and what it reads.
function streamOf(iterable) {
  const iterator = iterable[Symbol.asyncIterator]();
  return new ReadableStream({
    async pull(controller) {
      try {
        const { value, done } = await iterator.next();
        if (done) controller.close();
        else controller.enqueue(value);
      } catch (error) {
        controller.error(error);
      }
    },
    async cancel() {
      if (typeof iterator.return === "function") await iterator.return();
    },
  });
}

async function* read(stream) {
  if (!stream) return;
  const reader = stream.getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      yield value;
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // already closed
    }
    reader.releaseLock();
  }
}

function withCrowkis(agent, { crowkis = null, options = {} } = {}) {
  const lk = require("@livekit/agents");
  const { AudioFrame } = require("@livekit/rtc-node");
  const ownLlm = agent.llmNode.bind(agent);
  const ownTts = agent.ttsNode.bind(agent);
  let session = crowkis;
  let clips = null;
  let ownsVoice = false;
  const hits = new Map(); // cached answer text -> its audio, for the ttsNode that speaks it
  const pending = new Map(); // new answer text -> its turn, saved once a TTS run speaks it
  const toolTurns = new Map(); // question -> the turn a tool's answer belongs to
  let unspoken = false; // a cache hit decided but not (yet) spoken

  const crowkisSession = () => (session = session || voiceSession(options));
  const ttsOf = () => {
    try {
      return (agent._agentActivity && agent._agentActivity.tts) || agent.tts || null;
    } catch {
      return null;
    }
  };
  const clipCache = () => {
    const core = crowkisSession();
    clips = clips || new AudioClips(core, 0);
    const tts = ttsOf();
    if (tts) {
      if (tts.sampleRate > 0) clips.sampleRate = tts.sampleRate;
      const v = voiceOf(tts);
      if (v && (core._textOnly || ownsVoice)) {
        core.voice = v;
        core._textOnly = false;
        ownsVoice = true;
      }
    }
    return clips;
  };
  const instructionsOf = (chatCtx) => leadingInstructions(chatCtx).map(textOf).filter(Boolean).join("\n");
  const modelContext = (chatCtx, chosen) =>
    new lk.llm.ChatContext([
      ...leadingInstructions(chatCtx),
      ...chosen.map((m) => lk.llm.ChatMessage.create({ role: m.role, content: [m.content] })),
    ]);
  const clipAllowed = async (outcome) => {
    if (outcome !== "saved") return false;
    const crowkisAgent = crowkisSession().agent;
    return !((await crowkisAgent.decides()) && crowkisAgent._holds);
  };
  const save = async (turn, answer) => {
    const core = crowkisSession();
    const { outcome } = await core._record(turn.question, answer, {
      turn: turn.decision.turn,
      ...(turn.instructions ? { instructions: turn.instructions } : {}),
    });
    turn.decision._recorded = true;
    turn.decision._said = null;
    await clipCache().settle(answer, await clipAllowed(outcome));
    return outcome;
  };

  async function* replies(chatCtx, toolCtx, modelSettings) {
    const core = crowkisSession();
    const [question, after, userIndex] = lastUser(chatCtx);
    const instructions = instructionsOf(chatCtx);
    const cache = clipCache();
    const passThrough = async function* (ctx) {
      const parts = [];
      for await (const chunk of read(await ownLlm(ctx, toolCtx, modelSettings))) {
        parts.push(chunkText(chunk));
        yield chunk;
      }
      return parts.join("").trim();
    };

    if (question !== null && after.some(isTool)) {
      // The answer after a tool's result: right for this call only.
      const answer = yield* passThrough(chatCtx);
      const turn = toolTurns.get(question);
      if (turn && answer && !turn.toolRecorded) {
        turn.toolRecorded = true;
        await core._record(question, answer, { turn: turn.decision.turn, private: true, ...(instructions ? { instructions } : {}) });
      }
      return;
    }
    if (question === null || !question.trim() || after.length) {
      yield* passThrough(chatCtx); // not a reply to what the caller just said
      return;
    }
    if (unspoken && ttsOf()) core.cancel(); // the last hit was never spoken (a discarded attempt)
    unspoken = false;
    if (extraContext(chatCtx, userIndex)) {
      const answer = yield* passThrough(chatCtx);
      if (answer) core.recordPrivateTurn(question, answer);
      return;
    }

    const decision = await core.decide(question);
    if (!decision.needsModel) {
      let audio = decision.audio && core.audioFormat === `pcm16-${cache.sampleRate}` ? decision.audio : null;
      if (!audio && decision.audioShareable) audio = await cache.get(decision.text);
      if (audio) hits.set(decision.text.trim(), audio);
      else if (decision.audioShareable) cache.expect(decision.text, { shareable: true });
      unspoken = true;
      yield decision.text;
      return;
    }
    const turn = { decision, question, instructions, toolRecorded: false };
    toolTurns.clear();
    toolTurns.set(question, turn);
    const messages = decision.messages === null ? chatCtx : modelContext(chatCtx, decision.messages);
    const slot = cache.reserve(null, { trusted: true });
    const parts = [];
    let calledTool = false;
    let ended = false;
    try {
      for await (const chunk of read(await ownLlm(messages, toolCtx, modelSettings))) {
        parts.push(chunkText(chunk));
        if (chunkCallsTool(chunk)) calledTool = true;
        yield chunk;
      }
      ended = true;
    } finally {
      if (!ended) cache.release(slot); // cancelled while written: no run, no clip
    }
    const answer = parts.join("").trim();
    if (calledTool || !answer) {
      cache.release(slot);
      if (!answer && !calledTool) await core.record(decision, "");
      return;
    }
    slot[0] = answer;
    if (!ttsOf()) {
      await save(turn, answer); // no TTS: nothing will speak it, so it is saved now
      return;
    }
    pending.set(answer, turn);
    while (pending.size > 8) pending.delete(pending.keys().next().value);
  }

  async function* speech(text, modelSettings) {
    const cache = clipCache();
    const source = text[Symbol.asyncIterator] ? text : read(text);
    const it = source[Symbol.asyncIterator]();
    // Read while what this run says is still the start of a cached answer with audio: it
    // is that answer only if all of it is.
    const buffered = [];
    let ended = false;
    for (;;) {
      const sofar = buffered.join("");
      if (buffered.length && ![...hits.keys()].some((t) => t.startsWith(sofar.trim()) || same(t, sofar))) break;
      const r = await it.next();
      if (r.done) {
        ended = true;
        break;
      }
      buffered.push(r.value);
    }
    const hitText = ended ? [...hits.keys()].find((t) => same(t, buffered.join(""))) : undefined;
    const hit = hitText !== undefined ? hits.get(hitText) : null;
    if (hit) {
      // This run speaks a cached answer whose audio Crowkis has: played without the TTS.
      hits.delete(hitText);
      unspoken = false;
      const tts = ttsOf();
      const channels = (tts && tts.numChannels) || 1;
      const rate = cache.sampleRate || 24000;
      const step = Math.max(2 * channels, Math.floor((rate * FRAME_MS) / 1000) * 2 * channels);
      for (let start = 0; start < hit.length; start += step) {
        const chunk = hit.subarray(start, start + step);
        const samples = Math.floor(chunk.length / (2 * channels));
        if (!samples) continue;
        const pcm = new Int16Array(chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + samples * 2 * channels));
        yield new AudioFrame(pcm, rate, channels, samples);
      }
      return;
    }
    const spoken = [];
    async function* heard() {
      for (const piece of buffered) {
        spoken.push(piece);
        yield piece;
      }
      if (ended) return;
      for (let r = await it.next(); !r.done; r = await it.next()) {
        spoken.push(r.value);
        yield r.value;
      }
    }
    cache.ttsStarted();
    let finished = false;
    try {
      for await (const frame of read(await ownTts(heard(), modelSettings))) {
        const data = frame.data;
        cache.ttsAudio(Buffer.from(data.buffer, data.byteOffset, data.byteLength));
        yield frame;
      }
      finished = true;
    } finally {
      if (!finished) cache.interrupted(); // cut off: no clip, and nothing saved
    }
    const said = spoken.join("");
    unspoken = false;
    const answer = [...pending.keys()].find((a) => same(a, said));
    if (answer !== undefined) {
      const turn = pending.get(answer);
      pending.delete(answer);
      await save(turn, answer); // spoken in full: saved, and its clip ruled on
    }
    cache.ttsText(said);
    await cache.ttsStopped();
  }

  agent.llmNode = async (chatCtx, toolCtx, modelSettings) => streamOf(replies(chatCtx, toolCtx, modelSettings));
  agent.ttsNode = async (text, modelSettings) => streamOf(speech(text, modelSettings));
  Object.defineProperty(agent, "crowkis", { get: crowkisSession, configurable: true });
  return agent;
}

module.exports = { withCrowkis };
