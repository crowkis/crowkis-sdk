"use strict";

// The turn frame: what turn understanding says about one caller turn. Mirrors crowkis/turn.py.
//
// A model reads the caller's turn, the agent's last reply and the call state, and returns a
// frame. Everything downstream works on this structure, never on the raw words. Parsing is
// fail-closed: anything missing or malformed reads as "not shareable".

const KINDS = ["general", "personal", "live", "action", "dialogue", "chitchat", "sensitive", "unclear"];
const SUBJECTS = ["none", "self", "other"];
const QUESTION_TYPES = ["policy", "how_to", "product_fact", "place_fact", "search", "other"];
// Entity types whose text identifies a person: never allowed in a shared key.
const IDENTIFYING_TYPES = new Set(["person_name", "id_number", "contact", "address", "payment", "date_of_birth"]);
// Entity types that make a turn about someone in particular, whatever its kind says.
const NOT_GENERAL_TYPES = new Set(["owned_record", "own_purchase", "other_person"]);
// Non-identifying details worth remembering for later turns ("condition: damaged").
const DETAIL_TYPES = new Set(["product", "plan_product", "condition", "time", "quantity", "place"]);

function text(value) {
  return value === null || value === undefined ? "" : String(value).split(/\s+/).filter(Boolean).join(" ");
}

function bool(value) {
  if (typeof value === "string") return ["true", "yes", "1"].includes(value.trim().toLowerCase());
  return Boolean(value);
}

class Entity {
  constructor({ text: t, type, identifying, answerRelevant }) {
    this.text = t;
    this.type = type;
    this.identifying = identifying;
    this.answerRelevant = answerRelevant;
  }

  static fromDict(data) {
    const type = text(data.type).toLowerCase() || "topic";
    // The type decides identifying-ness; a model saying otherwise is overruled.
    return new Entity({
      text: text(data.text),
      type,
      identifying: IDENTIFYING_TYPES.has(type) || bool(data.identifying),
      answerRelevant: bool(data.answer_relevant ?? data.answerRelevant),
    });
  }
}

class Attribute {
  constructor({ value, normalised, changesAnswer }) {
    this.value = value;
    this.normalised = normalised;
    this.changesAnswer = changesAnswer;
  }

  static fromDict(data) {
    if (typeof data === "string") data = { value: data };
    if (!data || typeof data !== "object") return null;
    const value = text(data.value).toLowerCase();
    if (!value || value === "none") return null;
    const normalised = text(data.normalised ?? data.normalized).toLowerCase() || value;
    return new Attribute({ value, normalised, changesAnswer: bool(data.changes_answer ?? data.changesAnswer) });
  }
}

class TurnFrame {
  constructor(fields) {
    Object.assign(this, fields);
  }

  /** Read a model's output. Unknown or missing fields resolve to the safe side. */
  static fromDict(data) {
    data = data && typeof data === "object" && !Array.isArray(data) ? data : {};
    let kind = text(data.kind).toLowerCase();
    kind = KINDS.includes(kind) ? kind : "unclear";
    let subject = text(data.subject).toLowerCase();
    subject = SUBJECTS.includes(subject) ? subject : kind === "general" ? "none" : "self";
    let confidence = Number(data.confidence ?? 0);
    confidence = Number.isFinite(confidence) ? Math.min(1, Math.max(0, confidence)) : 0;
    const entities = (Array.isArray(data.entities) ? data.entities : [])
      .filter((e) => e && typeof e === "object").map((e) => Entity.fromDict(e));
    const attributes = {};
    for (const [name, raw] of Object.entries(data.attributes && typeof data.attributes === "object" ? data.attributes : {})) {
      const attr = Attribute.fromDict(raw);
      if (attr) attributes[String(name).toLowerCase()] = attr;
    }
    const question = text(data.question);
    const qtype = text(data.question_type ?? data.questionType).toLowerCase();
    return new TurnFrame({
      kind,
      urgent: bool(data.urgent),
      subject,
      taskStep: bool(data.task_step ?? data.taskStep),
      confidence,
      abstain: bool(data.abstain),
      entities,
      attributes,
      usesState: bool(data.uses_state ?? data.usesState),
      question: question && question !== "-" ? question : null,
      questionType: QUESTION_TYPES.includes(qtype) ? qtype : "other",
    });
  }

  get identifyingTexts() {
    return this.entities.filter((e) => e.identifying && e.text).map((e) => e.text);
  }

  /** Non-identifying, answer-relevant details (checked against the key). */
  get details() {
    return this.entities.filter((e) => DETAIL_TYPES.has(e.type) && e.answerRelevant && !e.identifying && e.text);
  }

  /** Non-identifying details a later turn may refer back to, whether or not they mattered now. */
  get memorable() {
    return this.entities.filter((e) => (DETAIL_TYPES.has(e.type) || e.type === "topic") && !e.identifying && e.text);
  }

  /** Thanks, "okay", "hold on": must not change the call state. A greeting that names a place does. */
  get isPureAcknowledgement() {
    if (this.kind !== "chitchat" && this.kind !== "dialogue") return false;
    return !this.memorable.length && !Object.keys(this.attributes).length && !this.taskStep && !this.usesState;
  }
}

module.exports = {
  TurnFrame, Entity, Attribute, KINDS, SUBJECTS, QUESTION_TYPES, IDENTIFYING_TYPES, NOT_GENERAL_TYPES, DETAIL_TYPES,
};
