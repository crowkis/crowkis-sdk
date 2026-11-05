"use strict";
const { CallState } = require("../../state/callState.js");
const { TurnFrame, FrameReading } = require("./frame.js");

// Turn understanding: one slot that turns a caller's sentence into a TurnFrame.
// Anything with `understand(turn, state)` (sync or async)
// plugs in; the voice rules still decide what is shared, so a weak model costs hits, never privacy.

function uncertain() {
  return TurnFrame.fromDict({ kind: "unclear", confidence: 0, abstain: true });
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
 "question_type": "policy|how_to|product_fact|place_fact|search|other",
 "language": "language code the reply must be in, e.g. en, hi, ta",
 "fact_relevance": [{"fact": "...", "type": "allergy|medication|pregnancy|age|diet|condition|trip|budget|other",
                     "changes_answer": true|false}]}

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
List every capitalised word, name or acronym of the turn as an entity with its type (a person's name is
person_name; CSV or SSO is topic; PayPal or MacBook is product).
A person's name is person_name however it is written (all capitals or lowercase); a word that acts like a
person ("Can McKenzie return items?") or that something is for ("returns for PRIYA") is a person, never a
product or place.
identifying: true only for what points to one person (a name, an ID, a contact, an address, a payment detail, a
birth date, an order or account number; where the caller lives is an address); a product, a topic, a place the
question is about, a plan or a condition is never identifying.
attributes: tier and location from the turn or the call state; changes_answer only if it changes the answer.
A location is where the user is (their city or country), never a place the question is about.
A segment is the customer's tier or plan (e.g. premium), never the topic of the question.
uses_state / abstain: resolve "it", "that", "the other place", ellipsis from the call state, the agent's mentions
and last reply. If the referent is not there, abstain = true and kind = dialogue. Never guess.
uses_state is false for a stand-alone question that only names a topic also in the call state.
question: only for general. Standalone and de-identified, built only from words in the turn, the agent's last reply
and the call state. Keep every product, place, condition, quantity, time and negation; drop names, IDs, contacts.
One sentence ending in "?", at most 25 words, generic voice ("How do I reset a password?").
language: the language the caller asked replies to be in (now, or earlier: call_state.language), otherwise the
language of the turn. Write the question in English whatever the turn's language; the reply language is separate.
question must also carry every fact in call_state.facts that changes the answer (an allergy, an age, a diet, a
trip) in generic words ("for someone with a peanut allergy", "for a 3-year-old").
How-to questions phrased with "my" ("How do I export my data?", "How do I reset my password?") are general with
subject none: the steps are the same for everyone. A question whose answer depends only on facts the caller told
(an allergy, an age, a diet, a trip, a budget) is general: put those facts in the question; personal is only for the
caller's own records, account, orders, bookings or identity.
If the turn asks for the same thing as call_state.active_question ("what were the steps again?"), return that
question exactly as it is written there. Facts about someone the caller mentions ("my mother has type 2 diabetes")
also make a later question general: "What foods should someone with type 2 diabetes avoid?".
fact_relevance: one entry for each fact in call_state.facts and each fact this turn states, "fact" written exactly
as given there. changes_answer is true if the answer to this turn could differ for someone with that fact (an allergy
and a dessert question, an age and a dose); false only when the answer is the same for everyone (a car accident and
"what is a deductible?"). When unsure, true.
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

/**
 * Adapter: reads a voice turn through an understander (LLMUnderstander over the app's `complete`
 * function, or any other). The model sees the turn, the call's facts (what earlier frames
 * remembered) and the turns in which the caller told it something (the same model already read them
 * as they were said), so it can say which of them change this answer. The stated turns are masked
 * (capitals, numbers, emails), not anonymised: plug in the app's own model, the one that already hears the call.
 */
class LLMClassifier {
  constructor(understander) {
    this._understander = understander;
  }

  /** The model's reading of the turn. */
  async classify(text, facts = []) {
    return new FrameReading(await this._understander.understand(text, new CallState({ facts })));
  }
}

/**
 * Adapter: keys a shareable turn on the understander's stand-alone, de-identified question. When the
 * classifier's reading already carries the model's frame (LLMClassifier over the same understander),
 * that frame is reused and the model is asked once per turn.
 */
class LLMRewriter {
  constructor(understander) {
    this._understander = understander;
  }

  /** The model's question for a turn that may be shared, else null (the caller's words). */
  async rewrite(text, reading) {
    if (reading.isPersonal) return null;
    if (reading instanceof FrameReading) return reading.question;
    return new FrameReading(await this._understander.understand(text, new CallState())).question;
  }
}

module.exports = {
  LLMUnderstander,
  WithFallback,
  INSTRUCTIONS,
  LLMClassifier,
  LLMRewriter,
};
