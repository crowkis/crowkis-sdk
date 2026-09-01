"use strict";

const USER = "user";

const ASSISTANT = "assistant";

const SERVED_ACTIONS = new Set(["serve", "filler"]);

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function own(node, key) {
  return Object.prototype.hasOwnProperty.call(node, key) ? node[key] : undefined;
}

function named(value, label) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(
      `${label} must be a non-empty string naming the event your realtime ` +
        "provider actually uses. A wrong or missing name means the gate never " +
        "fires, every turn is billed, and nothing reports it"
    );
  }
  return value.trim();
}

class RealtimeAdapter {
  constructor({
    transcriptEvent,
    transcriptField,
    injectEvent,
    respondEvent,
    roleField = "role",
    textField = "text",
  } = {}) {
    this.transcriptEvent = named(transcriptEvent, "transcriptEvent");
    this.transcriptField = named(transcriptField, "transcriptField");
    this.injectEvent = named(injectEvent, "injectEvent");
    this.respondEvent = named(respondEvent, "respondEvent");
    this.roleField = named(roleField, "roleField");
    this.textField = named(textField, "textField");
    const path = this.transcriptField.split(".").map((part) => part.trim());
    if (!path.every(Boolean)) {
      throw new Error(
        "transcriptField must be a field name or a dotted path to one, got " +
          JSON.stringify(transcriptField)
      );
    }
    this.transcriptPath = path;
  }

  isTranscript(event) {
    if (!isPlainObject(event)) return false;
    return (
      own(event, "type") === this.transcriptEvent ||
      Object.prototype.hasOwnProperty.call(event, this.transcriptEvent)
    );
  }

  transcriptOf(event) {
    if (!this.isTranscript(event)) return null;
    let node = event;
    for (const key of this.transcriptPath) {
      if (!isPlainObject(node)) return null;
      node = own(node, key);
    }
    return typeof node === "string" ? node : null;
  }

  inject(role, text) {
    return {
      type: this.injectEvent,
      [this.roleField]: role,
      [this.textField]: text,
    };
  }

  respond() {
    return { type: this.respondEvent };
  }

  toString() {
    return (
      `RealtimeAdapter(transcriptEvent='${this.transcriptEvent}', ` +
      `transcriptField='${this.transcriptField}')`
    );
  }
}

class RealtimeGate {
  constructor(session, adapter) {
    if (!(adapter instanceof RealtimeAdapter)) {
      throw new TypeError(
        "RealtimeGate needs a RealtimeAdapter carrying this provider's event names, " +
          `got ${adapter === null ? "null" : typeof adapter}`
      );
    }
    if (!session || typeof session.decide !== "function") {
      throw new TypeError(
        "RealtimeGate needs a VoiceSession to decide each turn, got " +
          `${session === null ? "null" : typeof session}`
      );
    }
    this.session = session;
    this.adapter = adapter;
    this.eventsSeen = 0;
    this.transcripts = 0;
    this.served = 0;
    this.forwarded = 0;
    this.suppressed = 0;
    this.pendingDecision = null;
  }

  get pendingAudio() {
    const audio = this.pendingDecision ? this.pendingDecision.audio : null;
    return audio === undefined ? null : audio;
  }

  async handle(event) {
    this.eventsSeen += 1;
    this.pendingDecision = null;

    if (!this.adapter.isTranscript(event)) return [];

    const transcript = this.adapter.transcriptOf(event);
    if (!transcript || !transcript.trim()) return this._forward();

    this.transcripts += 1;
    let decision;
    let events;
    try {
      decision = await this.session.decide(transcript);
      const action = decision === null || decision === undefined ? undefined : decision.action;
      const spoken = decision === null || decision === undefined ? undefined : decision.text;
      if (!SERVED_ACTIONS.has(action)) return this._forward();
      if (typeof spoken !== "string" || !spoken.trim()) return this._forward();
      events = [
        this.adapter.inject(USER, transcript),
        this.adapter.inject(ASSISTANT, spoken),
      ];
    } catch (e) {
      return this._forward();
    }

    this.pendingDecision = decision;
    this.served += 1;
    this.suppressed += 1;
    return events;
  }

  stats() {
    return {
      events: this.eventsSeen,
      transcripts: this.transcripts,
      served: this.served,
      forwarded: this.forwarded,
      suppressed: this.suppressed,
    };
  }

  _forward() {
    this.forwarded += 1;
    return [this.adapter.respond()];
  }

  toString() {
    return (
      `RealtimeGate(served=${this.served}, forwarded=${this.forwarded}, ` +
      `suppressed=${this.suppressed})`
    );
  }
}

module.exports = { RealtimeAdapter, RealtimeGate };
