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

// Copy a message template, putting values into "{role}"/"{text}" strings.
// Whole-string placeholders only, so a caller's words can never inject JSON
// structure or another placeholder into the message sent to the provider.
function render(template, values) {
  if (Array.isArray(template)) return template.map((v) => render(v, values));
  if (isPlainObject(template)) {
    const out = {};
    for (const [k, v] of Object.entries(template)) out[k] = render(v, values);
    return out;
  }
  if (typeof template === "string" && template.startsWith("{") && template.endsWith("}")) {
    const name = template.slice(1, -1);
    return Object.prototype.hasOwnProperty.call(values, name) ? values[name] : template;
  }
  return template;
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
    // Full messages with "{role}"/"{text}" placeholders at any depth, for
    // providers that nest the text (item.content[], turns[].parts[]).
    injectTemplate = null,
    respondTemplate = null,
    // The provider's name for the model's turns.
    assistantRole = ASSISTANT,
    // false when the provider already holds the caller's turn (server-side
    // voice activity detection commits the audio as an item).
    injectUser = true,
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
    this.injectTemplate = injectTemplate;
    this.respondTemplate = respondTemplate;
    this.assistantRole = named(assistantRole, "assistantRole");
    this.injectUser = Boolean(injectUser);
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
    if (this.injectTemplate !== null) return render(this.injectTemplate, { role, text });
    return {
      type: this.injectEvent,
      [this.roleField]: role,
      [this.textField]: text,
    };
  }

  respond(text = "") {
    if (this.respondTemplate !== null) return render(this.respondTemplate, { text });
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

  // The cached answer's audio for the app to play, handed over once. The
  // provider is never asked to speak it (that is a billed inference), so the
  // app plays it — and stops it on barge-in.
  takePendingAudio() {
    const audio = this.pendingAudio;
    this.pendingDecision = null;
    return audio;
  }

  async handle(event) {
    this.eventsSeen += 1;

    // Only an event carrying a transcript string is a turn. A provider that
    // nests transcription inside a general message type also sends audio and
    // turn markers under it; answering those with a respond started a new,
    // billed, self-interrupting response each.
    const transcript = this.adapter.transcriptOf(event);
    if (transcript === null) {
      const typed = isPlainObject(event) && own(event, "type") === this.adapter.transcriptEvent;
      return typed ? this._forward() : [];
    }
    this.pendingDecision = null;
    if (!transcript.trim()) return this._forward();

    this.transcripts += 1;
    let decision;
    let events;
    try {
      decision = await this.session.decide(transcript);
      const action = decision === null || decision === undefined ? undefined : decision.action;
      const spoken = decision === null || decision === undefined ? undefined : decision.text;
      if (!SERVED_ACTIONS.has(action)) return this._forward(transcript);
      if (typeof spoken !== "string" || !spoken.trim()) return this._forward(transcript);
      events = this.adapter.injectUser ? [this.adapter.inject(USER, transcript)] : [];
      events.push(this.adapter.inject(this.adapter.assistantRole, spoken));
    } catch (e) {
      return this._forward(transcript);
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

  _forward(transcript = "") {
    this.forwarded += 1;
    return [this.adapter.respond(transcript)];
  }

  toString() {
    return (
      `RealtimeGate(served=${this.served}, forwarded=${this.forwarded}, ` +
      `suppressed=${this.suppressed})`
    );
  }
}

module.exports = { RealtimeAdapter, RealtimeGate };
