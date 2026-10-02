"use strict";

// CallBridge: voice-pipeline logic for CallSession, independent of any framework.
// Mirrors crowkis/integrations/call_bridge.py.
//
//   onContext(messages, tools)  caller finished a turn -> play cached audio / speak text / call the model
//   onAnswer(text)              the model's full answer -> save if allowed
//   onTtsAudio(pcm)             TTS audio for the answer being spoken
//   onBotStopped()              the answer finished playing -> store its audio if allowed
//   onInterruption()            barge-in -> nothing from this turn is saved
//
// Audio is cached only for shared answers, recorded whole (from the first TTS chunk, kept only
// once the save is decided), never re-recorded from playback, keyed by voice, sample rate and
// format. Every cache call is bounded and wrapped: a failure means "no cached audio", never silence.

const { FILLER } = require("./session.js");
const { SHARED } = require("./verify.js");

const TTS_TOOL = "crowkis.tts.v2";
const TIMEOUT = Symbol("timeout");

function within(promise, ms) {
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(() => resolve(TIMEOUT), ms); });
  return Promise.race([Promise.resolve(promise), late]).finally(() => clearTimeout(timer));
}

function content(message) {
  const c = message.content ?? "";
  if (Array.isArray(c)) return c.filter((p) => p && typeof p === "object").map((p) => String(p.text ?? "")).join(" ");
  return String(c);
}

function newClip(fields = {}) {
  return { text: null, cacheable: false, pending: false, pcm: [], ...fields };
}

class CallBridge {
  constructor(session, { voice, sampleRate, audioFormat = "pcm16", audioBudgetMs = 150, audioTtl } = {}) {
    if (!String(voice || "").trim()) throw new Error("a voice id is required: cached audio is only reusable for the voice that made it");
    this.session = session;
    this.voice = String(voice).trim();
    this.sampleRate = Number(sampleRate);
    this.audioFormat = audioFormat;
    this.audioBudgetMs = audioBudgetMs;
    this.audioTtl = audioTtl;
    this.current = null;
    this._clip = newClip();
    this.counts = { audio_hits: 0, audio_misses: 0, audio_errors: 0, audio_saved: 0, errors: 0 };
  }

  async onContext(messages, tools = null) {
    this._clip = newClip();
    messages = messages || [];
    if (!messages.length || messages[messages.length - 1].role !== "user") {
      this.current = null;
      return { action: "model", messages: [...messages], tools };
    }
    let result;
    try {
      result = await this.session.handle(content(messages[messages.length - 1]));
    } catch {
      this.counts.errors += 1;
      this.current = null;
      return { action: "model", messages: [...messages], tools };
    }
    this.current = result;
    if (!result.needsModel && result.text) {
      const shareableAudio = result.route === SHARED || result.route === FILLER;
      const audio = shareableAudio ? await this._audioGet(result.text) : null;
      if (audio) return { action: "play_audio", text: result.text, audio, result };
      this._clip = newClip({ text: result.text, cacheable: shareableAudio });
      return { action: "speak_text", text: result.text, result };
    }
    if (result.messages !== null) {
      // A shared miss: keep the app's instructions and tools, replace only the call history.
      const system = messages.filter((m) => m.role === "system");
      this._clip = newClip({ pending: true }); // streaming TTS speaks before the answer is complete
      return { action: "model", messages: [...system, ...result.messages], tools, result };
    }
    return { action: "model", messages: [...messages], tools, result };
  }

  async onAnswer(text, { mentions = [], task = null } = {}) {
    const result = this.current;
    this.current = null;
    if (!result) return "not_recorded";
    let outcome;
    try {
      outcome = await this.session.recordAnswer(result, text, { mentions, task });
    } catch {
      this.counts.errors += 1;
      outcome = "refused:error";
    }
    const clip = this._clip.pending ? this._clip : newClip();
    clip.pending = false;
    clip.text = text;
    clip.cacheable = outcome === "saved";
    if (!clip.cacheable) clip.pcm = [];
    this._clip = clip;
    return outcome;
  }

  onTtsAudio(pcm) {
    if (this._clip.pending || (this._clip.cacheable && this._clip.text)) this._clip.pcm.push(Buffer.from(pcm));
  }

  async onBotStopped() {
    const clip = this._clip;
    this._clip = newClip();
    if (!(clip.cacheable && clip.text && clip.pcm.length)) return false;
    return this._audioSet(clip.text, Buffer.concat(clip.pcm));
  }

  onInterruption() {
    this._clip = newClip();
    this.current = null;
    this.session.cancel();
  }

  _key(text) {
    return JSON.stringify({ format: this.audioFormat, sample_rate: this.sampleRate, text, voice: this.voice });
  }

  _client() {
    return this.session.agent ? this.session.agent.client || null : null;
  }

  async _audioGet(text) {
    const client = this._client();
    if (!client) return null;
    let raw;
    try {
      raw = await within(client.ctoolget(TTS_TOOL, this._key(text), { tenant: this.session.agent.tenant }), this.audioBudgetMs);
    } catch {
      this.counts.audio_errors += 1;
      return null;
    }
    if (raw === TIMEOUT) { this.counts.audio_errors += 1; return null; }
    if (!raw) { this.counts.audio_misses += 1; return null; }
    const s = Buffer.isBuffer(raw) ? raw.toString("ascii") : String(raw);
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(s) || s.length % 4 !== 0) { this.counts.audio_errors += 1; return null; }
    const audio = Buffer.from(s, "base64");
    if (!audio.length) return null;
    this.counts.audio_hits += 1;
    return audio;
  }

  async _audioSet(text, pcm) {
    const client = this._client();
    if (!client) return false;
    try {
      await client.ctoolset(TTS_TOOL, this._key(text), pcm.toString("base64"), { ex: this.audioTtl, tenant: this.session.agent.tenant });
    } catch {
      this.counts.audio_errors += 1;
      return false;
    }
    this.counts.audio_saved += 1;
    return true;
  }
}

module.exports = { CallBridge, TTS_TOOL };
