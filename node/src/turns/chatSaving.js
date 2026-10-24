"use strict";

const { masked } = require("../understanding/chatDetails.js");
const { ChatAnswer } = require("./chatAnswer.js");
const { Checked } = require("./checked.js");
const { OUTCOME, because } = require("./outcome.js");
const { SHARED } = require("./routes.js");
const { Verdict } = require("./verdict.js");

const SAVED_COUNT = "saved";
const SAVE_REFUSED = "save_refused";
const NOT_SHARED = new Verdict("NotShared", "not a shared question the model answered", [], OUTCOME.NOT_SHARED);

/**
 * check(): the agent's reply is noted in the chat's state (names masked unless the question was
 * shared); only the model's answer to a shared question may be saved, and only past the save rules.
 * write(): agent.learn(), waited for no longer than twice the latency budget (BoundedWriter, as voice;
 * waited for without a budget), then the question it was saved for is kept. `session` is read live
 * (state, counts, agent, instructions, latencyBudgetMs, promptKey()).
 */
class ChatSaving {
  constructor(session, { saveRules, writer, questionRecords }) {
    this._session = session;
    this._saveRules = saveRules;
    this._writer = writer;
    this._questionRecords = questionRecords;
  }

  check(answered) {
    const { result, answer } = answered;
    const kept = result.route === SHARED ? answer : masked(answer);
    this._session.state.noteAgentReply(kept, answered.mentions, answered.task);
    if (result.route !== SHARED || result.text !== null || !result.verdict) return new Checked(answered, NOT_SHARED);
    const why = this.saveCheck(answer, result.verdict, result.frame, answered.private);
    if (why) return new Checked(answered, new Verdict("SaveCheck", why, [SAVE_REFUSED], because(OUTCOME.REFUSED, why)));
    return new Checked(answered);
  }

  async write(answered) {
    const { verdict } = answered.result;
    const answer = answered.answer;
    const learn = () => this._session.agent.learn(verdict.key, answer, {
      ttl: verdict.ttl ?? undefined, ...(verdict.segment ? { segment: verdict.segment } : {}),
    });
    const written = await this._writer.writeWithin(learn, this._session.latencyBudgetMs);
    if (!written.written) return written.objection.outcome;
    this._session.counts[SAVED_COUNT] += 1;
    this._questionRecords.keep(verdict.key, answer, verdict.ttl ?? null);
    return OUTCOME.SAVED;
  }

  /** Why an answer to a shared question must not be saved, or null. */
  saveCheck(answer, verdict, frame = null, isPrivate = false) {
    const session = this._session;
    const chatAnswer = new ChatAnswer(String(answer || "").split(/\s+/).filter(Boolean).join(" "), verdict, frame,
      session.state, { instructions: session.instructions, promptKey: session.promptKey(), private: isPrivate });
    const objection = this._saveRules.firstObjection(chatAnswer);
    return objection ? objection.reason : null;
  }
}

module.exports = { ChatSaving };
