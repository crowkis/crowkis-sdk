"use strict";

// What every voice framework adapter needs, with no framework in it: the Node side of
// python/crowkis/voice_turns.py, rule for rule (a shared scenario file checks that both
// do the same thing). Two pieces, driven by plain events that an adapter (LiveKit
// Agents, a custom loop) feeds from its own callbacks:
//
// AudioClips      keeps the spoken audio of an answer the cache shares, so the next hit
//                 skips the TTS too. A TTS run's audio belongs to the slot the run started
//                 with, so a clip is never stored under another answer's text; it is kept
//                 only when the TTS said that text (or the run is trusted by its order),
//                 and only once the answer's text is ruled shareable. Events: reserve /
//                 release / expect / vouch / settle, ttsStarted / ttsText / ttsAudio /
//                 ttsStopped, interrupted.
//
// AnswerPairing   hands each complete model answer to the session with the context it was
//                 generated from. The LLM answers contexts in the order it receives them,
//                 so each response is matched to its context: a caller's answer is paired
//                 with the question that is that context's last user message, and only
//                 while no tool is in flight; one that could be a tool's late answer is
//                 held until a later context settles it, and dropped if none does. A tool
//                 that never answers stops holding answers once the caller has moved on
//                 twice. An answer cut off by a barge-in is never stored. Events:
//                 queueContext, callerMovedOn, responseStart / responseText /
//                 responseEnd, toolCall, toolsDone, toolResult, interrupted.

const { _ttsKey: ttsKey, _storeLater: storeLater } = require("./agent.js");
const { _words: wordsOf } = require("./voice.js");

// Same tool name and key rule as Agent.speak().
const TTS_TOOL = "crowkis.tts";
// Answered caller turns a tool may say nothing through before it is taken as hung, and
// how many silent tools are remembered at most.
const HUNG_AFTER = 2;
const MAX_TOOLS = 4;
// Answers whose clip or ruling is still waiting for the other.
const WAITING = 4;
// TTS runs that may be reserved ahead of the one playing.
const RUNS_AHEAD = 16;

function field(message, name) {
  return message && typeof message === "object" ? message[name] : undefined;
}

// Python's truthiness, so a field that is empty ("", [], {}, 0) counts as absent exactly
// as in voice_turns.py.
function truthy(value) {
  if (Array.isArray(value)) return value.length > 0;
  if (value && typeof value === "object") return Object.keys(value).length > 0;
  return Boolean(value);
}

// The last user message's text, and the messages after it.
function lastUser(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (field(messages[index], "role") === "user") {
      const content = field(messages[index], "content");
      return [truthy(content) ? content : "", messages.slice(index + 1)];
    }
  }
  return [null, [...messages]];
}

// Whether a context carries a tool call or a tool's result after its last user message.
function toolContext(messages) {
  const [, after] = lastUser(messages);
  return after.some(
    (m) =>
      ["tool", "function"].includes(field(m, "role")) ||
      truthy(field(m, "tool_calls")) ||
      truthy(field(m, "function_call")) ||
      ["function_call", "function_call_output", "tool_use", "tool_result"].includes(field(m, "type"))
  );
}

// The system / developer messages in what the model read, as one text.
function instructionsOf(messages) {
  const parts = [];
  for (const message of messages || []) {
    if (!["system", "developer"].includes(field(message, "role"))) continue;
    const content = field(message, "content");
    if (typeof content === "string") parts.push(content);
    else if (Array.isArray(content)) parts.push(...content.map((p) => String(field(p, "text") || "")));
  }
  return parts.filter(Boolean).join("\n");
}

function remember(waiting, key, value) {
  waiting.delete(key);
  waiting.set(key, value);
  while (waiting.size > WAITING) waiting.delete(waiting.keys().next().value);
}

const sameWords = (a, b) => a.length === b.length && a.every((w, i) => w === b[i]);

class AudioClips {
  constructor(session, sampleRate) {
    this.session = session;
    this.sampleRate = sampleRate;
    this._pcm = [];
    // By answer text: finished clips waiting for a ruling, and rulings waiting for their
    // clip. The TTS can finish before or after the write-back has ruled.
    this._clips = new Map();
    this._rulings = new Map();
    // One slot per TTS run still to come, in the order the runs will happen: [text, trusted].
    this._runs = [];
    this._run = null; // the slot of the TTS run in progress
    this._unsynced = false;
    this._spoken = []; // what that run said, where the TTS reports it
  }

  _labels() {
    const s = this.session;
    const format = s.audioFormat !== "default" ? s.audioFormat : `pcm16-${this.sampleRate}`;
    return [s.voice, s.language, String(s.speed), format];
  }

  _key(text) {
    return ttsKey(text, this._labels());
  }

  _usesAudioCache(text) {
    const agent = this.session.agent;
    return Boolean(typeof agent._audioCacheUsable === "function" && agent._audioCacheUsable(text, this._labels()));
  }

  async get(text) {
    if (this.session._textOnly) return null; // no voice id to key a clip on
    if (!this.sampleRate) return null; // no TTS has said its sample rate
    const agent = this.session.agent;
    if (this._usesAudioCache(text)) {
      try {
        const clip = await agent.client.caudioget(text, ...this._labels(), { tenant: agent.tenant });
        agent._audioV2 = true;
        return clip && clip.length ? clip : null;
      } catch (error) {
        const [use] = agent._audioCacheFailed(error);
        if (use) return null;
      }
    }
    let raw;
    try {
      raw = await agent.client.ctoolget(TTS_TOOL, this._key(text), { tenant: agent.tenant });
    } catch (error) {
      agent._audioCacheError("read", error); // a failed read is a miss, never the end of the turn
      return null;
    }
    if (!raw) return null;
    // Strict: a damaged clip is a miss, never noise played to the caller.
    const encoded = Buffer.isBuffer(raw) ? raw.toString("utf8") : String(raw);
    const clip = Buffer.from(encoded, "base64");
    return clip.length && clip.toString("base64") === encoded ? clip : null;
  }

  // Name the answer that the next TTS run speaks. shareable=true for an answer the cache
  // just served: its clip may be stored. Left out for a new answer: its clip waits for
  // settle(). A run named here is trusted by its order; naming another before it starts
  // replaces it.
  expect(text, { shareable } = {}) {
    this._runs = this._runs.filter((slot) => !slot[1]);
    this.reserve(text, { trusted: true });
    if (shareable !== undefined && shareable !== null) remember(this._rulings, text, shareable);
  }

  // Hold the place of a TTS run that is coming, in stream order; its text can be filled
  // in later (slot[0] = text), before the run ends. Unless trusted, its clip is kept only
  // when the TTS reports having spoken that text.
  reserve(text = null, { trusted = false } = {}) {
    const slot = [text, trusted];
    this._runs.push(slot);
    if (this._runs.length > RUNS_AHEAD) {
      // Far more runs waiting than a call ever has: keep no clip until a barge-in resets the order.
      this._runs = [];
      this._unsynced = true;
    }
    return slot;
  }

  // A reserved run that will not happen (an answer with nothing to speak).
  release(slot) {
    const at = this._runs.indexOf(slot);
    if (at >= 0) this._runs.splice(at, 1);
  }

  // An answer the cache served: its clip may be stored once its own run ends.
  vouch(text) {
    remember(this._rulings, text, true);
  }

  // The write-back's ruling on a new answer: store its clip, or drop it.
  async settle(text, shareable) {
    const clip = this._clips.get(text);
    this._clips.delete(text);
    if (clip === undefined) remember(this._rulings, text, shareable);
    else if (shareable) await this._store(text, clip);
  }

  // A barge-in: the run in progress and every reserved run are gone.
  interrupted() {
    this._pcm = [];
    this._run = null;
    this._spoken = [];
    this._unsynced = false;
    this._runs = [];
  }

  // A TTS run starts (one per answer, not per sentence): a new clip, for the next slot.
  ttsStarted() {
    this._pcm = [];
    this._spoken = [];
    this._run = this._runs.length ? this._runs.shift() : null;
  }

  // Words the run in progress spoke, where the TTS reports them.
  ttsText(text) {
    if (this._run !== null) this._spoken.push(text || "");
  }

  ttsAudio(pcm) {
    this._pcm.push(Buffer.from(pcm));
  }

  async ttsStopped() {
    const run = this._run;
    this._run = null;
    const text = run ? run[0] : null;
    const clip = Buffer.concat(this._pcm);
    const spoken = wordsOf(this._spoken.join(" "));
    this._pcm = [];
    this._spoken = [];
    if (!(text && clip.length) || this._unsynced) return;
    if (spoken.length && !sameWords(spoken, wordsOf(text).slice(0, spoken.length))) return; // said something else
    if (!spoken.length && !run[1]) return; // fail closed: the TTS did not say what it spoke
    const ruling = this._rulings.get(text);
    this._rulings.delete(text);
    if (ruling === undefined) remember(this._clips, text, clip);
    else if (ruling) await this._store(text, clip);
  }

  async _store(text, clip) {
    if (this.session._textOnly) return; // no voice id to key a clip on
    if (!this.sampleRate) return; // no TTS has said its sample rate: the format is unknown
    const agent = this.session.agent;
    if (agent._audioV2 === true && this._usesAudioCache(text)) {
      // In the background: the next event is never held for a store.
      const ms = this.sampleRate ? Math.floor((clip.length * 1000) / (this.sampleRate * 2)) : undefined;
      const copy = Buffer.from(clip);
      storeLater(() =>
        agent.client.caudioset(text, ...this._labels(), copy, { ex: this.session.ttl, ms, tenant: agent.tenant })
      );
      return;
    }
    try {
      await agent.client.ctoolset(TTS_TOOL, this._key(text), Buffer.from(clip).toString("base64"), {
        ex: this.session.ttl,
        tenant: agent.tenant,
      });
    } catch (error) {
      agent._audioCacheError("written", error); // a failed write only costs a later hit
    }
  }
}

// `gate` is the adapter's turn gate: any object with `asked` (an array of the contexts
// sent to the LLM, oldest first: [kind, turn, question, messages] with kind "caller" or
// "tool", or null for one nobody can be paired with), and `question` / `messages` (for a
// gate that keeps no queue). `audio` is an AudioClips. `onAnswer(info)` is told what
// happened to each answer.
class AnswerPairing {
  constructor(session, gate, audio, { onAnswer = null } = {}) {
    this.session = session;
    this.gate = gate;
    this.audio = audio;
    this.onAnswer = onAnswer;
    this._parts = null;
    this._bound = null; // the context the response in progress was generated from
    this._held = false; // that response could be a tool's late answer: hold it until settled
    this._calling = false; // the response in progress asked for a tool
    this._pending = []; // [turn, question, messages] of tool calls whose answer is still to come
    this._moves = 0; // caller turns answered, unrecorded, while a tool said nothing
    this._hung = []; // tools taken as hung; a result from one re-arms it
    this._deferred = null; // [context, answer] of a held response
    this._slot = null; // the audio run reserved for the response in progress
    // The LLM service's own system instruction, which the model reads on every turn; an
    // adapter that knows it (as Python's Pipecat one does) sets it so answers repeating a
    // caller's detail from it are not shared.
    this.serviceInstructions = null;
  }

  async _reportAnswer(info) {
    if (this.onAnswer) await this.onAnswer(info);
  }

  // The LLM starts a response. Its TTS run is reserved in stream order; a gate with no
  // queue of contexts keeps the original contract: the run is trusted by its order.
  async responseStart() {
    this._slot = this.audio.reserve(null, { trusted: !Array.isArray(this.gate.asked) });
    await this._start();
  }

  responseText(text) {
    if (this._parts !== null) this._parts.push(text);
  }

  // A text the TTS is asked to say directly (a served answer, a fallback): its run, in order.
  speakRequested(text) {
    this.audio.reserve(text);
  }

  // The response in progress asked for a tool.
  toolCall() {
    this._calling = true;
  }

  // No answer will follow the tools in flight. Then call settle(true).
  toolsDone() {
    this._pending = [];
    this._hung = [];
  }

  // A tool's result that runs the LLM again. From a tool taken as hung: what follows is
  // its answer after all.
  toolResult() {
    if (!this._pending.length && this._hung.length) this._pending.push(this._hung.shift());
  }

  // A barge-in: the response in progress is never stored. Then call settle(false).
  interrupted() {
    this._parts = null;
    this._bound = null;
    this._calling = false;
    this._held = false;
    this._slot = null;
  }

  // The response is complete. Resolves to [context, answer] to record with record() once
  // the adapter has passed the end of the response on, or null when there is nothing to
  // record now (a tool call, a held answer, an unpaired one).
  async responseEnd() {
    if (this._parts === null) return null;
    const answer = this._parts.join("").trim();
    this._parts = null;
    const bound = this._bound;
    this._bound = null;
    const calling = this._calling;
    this._calling = false;
    const slot = this._slot;
    this._slot = null;
    if (slot !== null && answer) slot[0] = answer; // its clip waits for the ruling below
    else if (slot !== null) this.audio.release(slot);
    if (bound !== null && calling) {
      if (!this._pending.length) this._moves = 0;
      this._pending = [...this._pending, bound.slice(1)].slice(-MAX_TOOLS);
      await this.audio.settle(answer, false);
    } else if (bound !== null && bound[0] === "caller" && this._held) {
      this._deferred = [bound, answer];
    } else if (bound !== null) {
      return [bound, answer];
    } else {
      await this.audio.settle(answer, false);
    }
    return null;
  }

  // Queue a context the LLM will answer that the caller did not just say. True when a
  // held answer is now known to be the caller's own: settle(true) then.
  queueContext(messages) {
    if (!toolContext(messages)) {
      this.gate.asked.push(null);
      return false;
    }
    const [question] = lastUser(messages);
    const at = this._pending.findIndex((t) => t[1] === question);
    const tool = at >= 0 ? this._pending.splice(at, 1)[0] : null;
    this.gate.asked.push(["tool", tool ? tool[0] : null, question, messages]);
    return true;
  }

  // A new caller turn: a held response can no longer be told apart from a tool's. A tool
  // that has said nothing while two of the caller's turns were answered is taken as hung.
  async callerMovedOn() {
    if (this._pending.length && this._deferred !== null) this._moves += 1;
    if (this._pending.length && this._moves >= HUNG_AFTER) {
      this._hung = this._pending.slice(-MAX_TOOLS);
      this._pending = [];
      this._moves = 0;
    }
    await this.settle(false);
  }

  async _start() {
    this._parts = [];
    this._held = false;
    const asked = this.gate.asked;
    if (!Array.isArray(asked)) {
      this._bound = ["caller", null, this.gate.question, this.gate.messages];
      return;
    }
    if (this._deferred !== null) {
      // Two responses with no context between them while a tool was in flight: neither is
      // stored or paired.
      if (asked.length) asked.shift();
      else if (this._pending.length) this._pending.shift();
      this._bound = null;
      await this.settle(false);
      return;
    }
    if (asked.length) this._bound = asked.shift();
    else if (this._pending.length) this._bound = ["tool", ...this._pending.shift()];
    else this._bound = null;
    this._held = Boolean(
      this._bound &&
        this._bound[0] === "caller" &&
        (this._pending.length || asked.some((e) => e && e[0] === "tool"))
    );
  }

  // Record a held response as its caller's answer, or drop it.
  async settle(answered) {
    const deferred = this._deferred;
    this._deferred = null;
    if (deferred === null) return;
    if (answered) {
      await this.record(...deferred);
      return;
    }
    await this.audio.settle(deferred[1], false);
    await this._reportAnswer({
      question: "", answer: deferred[1], messages: [], saved: "not_saved",
      stored: false, notStored: "could not be told apart from a tool's late answer",
    });
  }

  async record(bound, answer) {
    const [kind, turn, question, messages] = bound;
    if (!question || (kind === "tool" && (turn === null || turn === undefined))) {
      await this.audio.settle(answer, false);
      return;
    }
    // The system messages the model read (and the LLM service's own instruction, where
    // the adapter knows it) are its instructions: an answer repeating a detail they give
    // about this caller is never shared.
    const instructions = [instructionsOf(messages), this.serviceInstructions || ""].filter(Boolean).join("\n");
    const extra = instructions ? { instructions } : {};
    const { outcome, why } =
      (turn === null || turn === undefined) && kind === "caller"
        ? await this.session._record(question, answer, extra)
        : await this.session._record(question, answer, { turn, private: kind === "tool", ...extra });
    await this.audio.settle(answer, await this._clipAllowed(outcome));
    const stored = outcome === "saved" || outcome === "template";
    await this._reportAnswer({
      question, answer, messages, saved: outcome, stored, notStored: stored ? "" : why || outcome,
    });
  }

  // Only an answer saved word for word, and not while the server's decision engine holds
  // answers until it vouches for them.
  async _clipAllowed(outcome) {
    if (outcome !== "saved") return false;
    const agent = this.session.agent;
    return !((await agent.decides()) && agent._holds);
  }
}

module.exports = { AudioClips, AnswerPairing, TTS_TOOL, _toolContext: toolContext, _lastUser: lastUser };
