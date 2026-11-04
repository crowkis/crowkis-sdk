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

// A language tag ("hi", "en", "pt-br"); anything else from a model is no language.
const LANGUAGE = /^[a-z]{2,3}(-[a-z0-9]{2,8})?$/;

function text(value) {
  return value === null || value === undefined ? "" : String(value).split(/\s+/).filter(Boolean).join(" ");
}

function bool(value) {
  if (typeof value === "string") return ["true", "yes", "1"].includes(value.trim().toLowerCase());
  return Boolean(value);
}

// A payment method named only in general ("a different card", "UPI", "my bank account") identifies no
// one: tagged as payment, it is not identifying unless it has a number or a name (v4, misfire B04).
const GENERIC_PAYMENT_WORDS = new Set([
  "a", "an", "the", "my", "another", "different", "other", "new", "same", "card", "cards", "credit", "debit",
  "upi", "wallet", "bank", "account", "net", "netbanking", "banking", "transfer", "cash", "cheque", "check",
  "payment", "method", "original", "emi",
]);

class Entity {
  constructor({ text: t, type, identifying, answerRelevant }) {
    this.text = t;
    this.type = type;
    this.identifying = identifying;
    this.answerRelevant = answerRelevant;
  }

  static fromDict(data) {
    const type = text(data.type).toLowerCase() || "topic";
    const said = text(data.text);
    // The type decides identifying-ness; a model saying otherwise is overruled. A payment method named
    // only in general is the one exception.
    const words = said.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
    const genericPayment = type === "payment" && words.length > 0 && words.every((w) => GENERIC_PAYMENT_WORDS.has(w));
    return new Entity({
      text: said,
      type,
      identifying: !genericPayment && (IDENTIFYING_TYPES.has(type) || bool(data.identifying)),
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

/**
 * Whether a fact the caller stated (an allergy, an age, a trip) changes the answer to this turn. Read
 * fail-closed: a fact the model did not say is irrelevant changes the answer.
 */
// What a model's "does not change the answer" may look like; anything else counts as "it does".
const SAID_NO = [false, 0, "false", "False", "no", "No", "0"];

class FactRelevance {
  constructor({ fact, type, changesAnswer }) {
    Object.assign(this, { fact, type, changesAnswer });
    Object.freeze(this);
  }

  static fromDict(data) {
    if (!data || typeof data !== "object") return null;
    const fact = text(data.fact);
    if (!fact) return null;
    // Only a plain "no" makes a fact irrelevant: missing, "unsure" or "maybe" means it counts.
    const said = data.changes_answer ?? data.changesAnswer;
    return new FactRelevance({ fact, type: text(data.type).toLowerCase() || "other", changesAnswer: !SAID_NO.includes(said) });
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
    const language = text(data.language).toLowerCase();
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
      // The language the reply must be in ("hi", "en"): asked for now or earlier, else the turn's.
      language: LANGUAGE.test(language) ? language : null,
      // For each fact the caller stated, whether it changes this turn's answer (v4 StatedFacts).
      factRelevance: (Array.isArray(data.fact_relevance ?? data.factRelevance) ? (data.fact_relevance ?? data.factRelevance) : [])
        .map((r) => FactRelevance.fromDict(r)).filter(Boolean),
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

// The frame kind a voice call may share: the same answer for every caller.
const SHAREABLE_KIND = "general";
// A turn that only means something next to the turn before it.
const FOLLOW_UP_KIND = "dialogue";
// Below this the frame is a guess, and a guess is read as private (Chat's rule checker uses the same floor).
const CONFIDENCE_FLOOR = 0.6;

/**
 * What a model made of a turn, as the voice rules read it. Anything but a confident, general turn
 * about no one in particular reads as personal: a weak or unsure model costs cache hits, never
 * privacy. `frame` is kept so the rewriter reuses it instead of asking the model again.
 */
class FrameReading {
  constructor(frame) {
    this.frame = frame;
  }

  /** Not a confident, general question: never shared. */
  get isPersonal() {
    const frame = this.frame;
    return frame.kind !== SHAREABLE_KIND || frame.abstain || frame.urgent || frame.subject !== "none" ||
      frame.confidence < CONFIDENCE_FLOOR || frame.identifyingTexts.length > 0;
  }

  /** The model needed the call so far to read it. */
  get isContextDependent() {
    return this.frame.usesState || this.frame.kind === FOLLOW_UP_KIND;
  }

  /** The stand-alone question to look the turn up with, only for a turn that may be shared. */
  get question() {
    return this.isPersonal ? null : this.frame.question;
  }
}

module.exports = {
  TurnFrame,
  Entity,
  Attribute,
  FactRelevance,
  KINDS,
  SUBJECTS,
  QUESTION_TYPES,
  IDENTIFYING_TYPES,
  NOT_GENERAL_TYPES,
  DETAIL_TYPES,
  FrameReading,
  CONFIDENCE_FLOOR,
};
