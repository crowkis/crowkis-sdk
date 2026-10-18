"use strict";

// Turn understanding: one slot that turns a caller's sentence into a TurnFrame.
// Mirrors crowkis/understand.py. Anything with `understand(turn, state)` (sync or async)
// plugs in; the rule checker still decides what is shared, so a weak model costs hits, never privacy.

const { TurnFrame } = require("./turn.js");

function uncertain() {
  return TurnFrame.fromDict({ kind: "unclear", confidence: 0, abstain: true });
}

/** Case, punctuation and spacing never make two wordings different; words always do. */
function normalise(t) {
  return String(t || "").toLowerCase().replace(/[!"#$%&()*+,\-./:;<=>?@[\\\]^_`{|}~]/g, " ").split(/\s+/).filter(Boolean).join(" ");
}

/** Recognises only exact repeats of already-verified questions: the safe fallback with no model. */
class ReplayUnderstander {
  constructor(known = {}) {
    this._known = new Map();
    for (const [question, qtype] of Object.entries(known)) this.remember(question, question, qtype);
  }

  remember(turn, question, questionType = "other") {
    for (const wording of [turn, question]) {
      const key = normalise(wording);
      if (key) this._known.set(key, [question, questionType]);
    }
  }

  understand(turn) {
    const hit = this._known.get(normalise(turn));
    if (!hit) return uncertain();
    return TurnFrame.fromDict({ kind: "general", subject: "none", confidence: 1, question: hit[0], question_type: hit[1] });
  }

  get size() {
    return this._known.size;
  }
}

/** Use `primary`; if it throws or returns nothing usable, use `fallback`. */
class WithFallback {
  constructor(primary, fallback) {
    this.primary = primary;
    this.fallback = fallback;
    this.primaryFailures = 0;
  }

  async understand(turn, state) {
    let frame = null;
    try {
      frame = await this.primary.understand(turn, state);
    } catch {
      frame = null;
    }
    if (!frame || (frame.kind === "unclear" && frame.confidence === 0)) {
      this.primaryFailures += 1;
      return this.fallback.understand(turn, state);
    }
    return frame;
  }
}

const INSTRUCTIONS = `You are a turn-understanding model for a customer-support agent. You do not answer the caller.
You describe the caller's latest turn as one JSON object, using only: the turn, the agent's last reply, and the
call state (what was established earlier). Never invent facts the caller or agent did not say.

Return exactly:
{"kind": "general|personal|live|action|dialogue|chitchat|sensitive|unclear",
 "urgent": true|false, "subject": "none|self|other", "task_step": true|false,
 "confidence": 0.0-1.0, "abstain": true|false,
 "entities": [{"text": "...", "type": "...", "identifying": true|false, "answer_relevant": true|false}],
 "attributes": {"segment": {"value": "...", "changes_answer": true|false},
                "region": {"value": "...", "normalised": "...", "changes_answer": true|false}},
 "uses_state": true|false,
 "question": "standalone question, or -",
 "question_type": "policy|how_to|product_fact|place_fact|search|other"}

kind: general = the same answer for every caller from the business's own knowledge (policies, how-to,
troubleshooting, product facts, stable facts about a named place, searches with stable criteria). personal = about
this caller or another specific person (their records, purchases, account, eligibility, identity, details they
give). live = fast-changing data (stock, outages, open now, availability for a date, changing prices). action = asks
the agent to do or change something. dialogue = only meaningful against the previous turn (answers to the agent's
question, confirmations, corrections, choosing, repeats, complaints, steering). chitchat = greetings, thanks,
goodbyes. sensitive = medical, legal, financial or safety advice; emergencies. unclear = garbled or out of scope.
With two substantive parts: action > personal > live > sensitive > dialogue > unclear > chitchat > general.
Greetings, thanks and self-introductions attached to a question are noise.
urgent: an emergency or crisis that needs immediate help.
task_step: the turn gives details for a task the agent is running (booking, ordering, account change), such as
dates, party size, budget or preferences in reply to the agent's question.
entities types: person_name, id_number, contact, address, payment, date_of_birth (identifying); owned_record,
own_purchase, other_person, place, tier, product, plan_product, quantity, time, condition, topic.
attributes: tier and location from the turn or the call state; changes_answer only if it changes the answer.
uses_state / abstain: resolve "it", "that", "the other place", ellipsis from the call state, the agent's mentions
and last reply. If the referent is not there, abstain = true and kind = dialogue. Never guess.
question: only for general. Standalone and de-identified, built only from words in the turn, the agent's last reply
and the call state. Keep every product, place, condition, quantity, time and negation; drop names, IDs, contacts.
One sentence ending in "?", at most 25 words, generic voice ("How do I reset a password?").
confidence: your calibrated probability that kind and question are right.`;

function extractJson(t) {
  if (!t) return null;
  try {
    const data = JSON.parse(t);
    return data && typeof data === "object" && !Array.isArray(data) ? data : null;
  } catch {
    const m = String(t).match(/\{[\s\S]*\}/);
    if (!m) return null;
    try {
      const data = JSON.parse(m[0]);
      return data && typeof data === "object" && !Array.isArray(data) ? data : null;
    } catch {
      return null;
    }
  }
}

/** Interim understander over the app's own LLM: `complete(messages) -> string | Promise<string>`. */
class LLMUnderstander {
  constructor(complete, { business = "" } = {}) {
    this.complete = complete;
    this.business = String(business || "").trim();
  }

  messages(turn, state) {
    const system = INSTRUCTIONS + (this.business ? "\n\nBUSINESS:\n" + this.business : "");
    return [
      { role: "system", content: system },
      { role: "user", content: JSON.stringify({ call_state: state.snapshot(), turn }) },
    ];
  }

  async understand(turn, state) {
    const data = extractJson(await this.complete(this.messages(turn, state)));
    return data ? TurnFrame.fromDict(data) : uncertain();
  }
}

module.exports = { ReplayUnderstander, LLMUnderstander, WithFallback, INSTRUCTIONS, normalise };
