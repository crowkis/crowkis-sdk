"use strict";

const { COUNTER } = require("../runtime/stats.js");
const {
  AMOUNT_WORDS, EMAIL, MATTERS, SLOT, abstract, carriesCallContext, hasDigit, identifies, leaks, readsOutDigits,
  slotNames, wordsOf,
} = require("../understanding/wordRules/index.js");
const { Checked } = require("./checked.js");
const { ModelAnswer } = require("./modelAnswer.js");
const { OUTCOME } = require("./outcome.js");
const { isThenable } = require("./turnCore.js");

/**
 * check(): the answer as the save rules read it: `answerGiven` first, then, once it is known to be an
 * answer, its cache key and its place in the transcript, then `beforeSharing`.
 * write(): the shared form of the answer and its write (the writer's boundary turns a failed one into
 * the refused outcome): a personal
 * answer only as a shape with this call's values taken out (`personal`, and only when the session
 * shares templates), any other after the `sharing` rules; through the bounded write (in the call's
 * `segment`, if any), with the question it was saved for. `lastStored` is the question the latest
 * shared answer was stored under. `session` is read live (agent, latencyBudgetMs, ttl, shareTemplates,
 * values, transcript): an app may change them between turns.
 */
class VoiceSaving {
  constructor(session, { rules, call, state, report, writer, stats, segment }) {
    this._session = session;
    this._rules = rules;
    this._call = call;
    this._state = state;
    this._report = report;
    this._writer = writer;
    this._stats = stats;
    this._segment = segment;
    this.lastStored = null;
  }

  check(answered) {
    const answer = new ModelAnswer(answered.said, answered.modelSaid, null, this._call, {
      private: answered.private, instructions: answered.instructions, cacheable: answered.shareable && !answered.private,
    });
    const verdict = this._rules.answerGiven.firstObjection(answer);
    if (isThenable(verdict)) return verdict.then((given) => (given ? new Checked(answer, given) : this._keyed(answered, answer)));
    if (verdict) return new Checked(answer, verdict);
    return this._keyed(answered, answer);
  }

  async write(answer) {
    if (answer.isPersonal) return await this._writePersonal(answer);
    let verdict = this._rules.sharing.firstObjection(answer);
    if (isThenable(verdict)) verdict = await verdict;
    if (verdict) return this._report.kept(verdict);
    const written = await this._learn(answer.key, answer.answer, { ttl: this._session.ttl });
    if (written.refused) return this._report.refused(written.error);
    if (!(written.objection && written.objection.rule === "NotStored")) this.lastStored = answer.key; // a key the server kept nothing under is not waited for
    if (!written.written) return this._report.kept(written.objection); // a slow server gets no extra write
    this._call.questionRecords().keep(answer.key, answer.answer, this._session.ttl);
    return { outcome: OUTCOME.SAVED, why: "", rule: null };
  }

  // Once it is known to be an answer: its cache key (worked out before it joins the transcript), then
  // its place in the transcript; `beforeSharing`'s objection may still be pending.
  _keyed(answered, answer) {
    answer.key = this._state.rewrittenFor(answer.text) ?? this._call.contextKey(answered.said, answer.text);
    this._session.transcript.push({ role: "user", content: answered.said });
    this._session.transcript.push({ role: "assistant", content: answered.modelSaid });
    return new Checked(answer, this._rules.beforeSharing.firstObjection(answer));
  }

  // agent.learn() through the bounded write (twice the latency budget; waited for without one), in the
  // call's segment; resolves to a WriteResult. Not async: the caller awaits the writer's own promise,
  // with no extra step between.
  _learn(key, answer, options) {
    const learnOptions = this._segment ? { segment: this._segment, ...options } : options;
    return this._writer.writeWithin(() => this._session.agent.learn(key, answer, learnOptions), this._session.latencyBudgetMs);
  }

  // A personal answer is shared only as a shape with this call's values taken out.
  async _writePersonal(answer) {
    const personal = this._rules.personal;
    let verdict = personal.check(answer);
    if (!verdict) {
      const templated = await this._learnPersonal(answer.key, answer.answer);
      if (templated === null) verdict = personal.refusal();
      else if (templated.written) return { outcome: OUTCOME.TEMPLATE, why: "", rule: null };
      else if (templated.refused) return this._report.refused(templated.error);
      else verdict = templated.objection; // slow_write: the shape was not confirmed written
    }
    return this._report.kept(verdict);
  }

  // Store a personal answer as a shape: what the write did (a WriteResult), or null (nothing written)
  // when it cannot be made generic, or when this session does not share templates.
  async _learnPersonal(keyed, modelSaid) {
    const session = this._session;
    if (!session.shareTemplates) {
      this._stats.add(COUNTER.UNCACHEABLE_PERSONAL);
      return null;
    }
    const shaped = abstract(modelSaid, session.values);
    // The model read the whole call: what is left outside the slots must say nothing
    // of this caller that was not declared (a name, an address, a number, a matter).
    const outside = shaped.replace(SLOT, " ");
    const words = wordsOf(outside);
    const earlier = session.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    const undeclared =
      words.some((w) => hasDigit(w) || AMOUNT_WORDS.has(w) || MATTERS.has(w)) ||
      readsOutDigits(outside, words) || EMAIL.test(outside) || identifies(outside, words) ||
      carriesCallContext(outside, keyed, earlier);
    if (this._call.hasValues && slotNames(shaped).length && !leaks(shaped, session.values) && !undeclared) {
      return await this._learn(keyed, shaped, { ttl: session.ttl, template: true });
    }
    this._stats.add(COUNTER.UNCACHEABLE_PERSONAL);
    return null;
  }
}

module.exports = { VoiceSaving };
