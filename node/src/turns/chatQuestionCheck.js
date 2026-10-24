"use strict";

const { Verdict: ChatVerdict } = require("../rules/ruleChecker.js");
const { privateWords } = require("../understanding/chatDetails.js");
const { ChatTurn } = require("./chatTurn.js");
const { Checked } = require("./checked.js");
const { AGENT, URGENT } = require("./routes.js");
const { Verdict } = require("./verdict.js");

const CHECK_RULE = "ChatQuestionCheck";

/**
 * The rule checker (V1-V10, every objection reported) keys a shareable question; then, on what the
 * chat has learnt, the shared-question rules may still keep it with the agent, and the fixed urgent
 * words send a turn about the user to the urgent route whatever the model said. The chat's state
 * takes the turn in, and its route is counted. A shared question is remembered by the safe fallback;
 * any other route is the objection (the model answers with the whole chat). `session` is read live
 * (state, counts, checker, replay).
 */
class ChatQuestionCheck {
  constructor(session, { sharedQuestionRules, urgentWords }) {
    this._session = session;
    this._sharedQuestionRules = sharedQuestionRules;
    this._urgentWords = urgentWords;
  }

  checkQuestion(reading) {
    const verdict = this._verdict(reading);
    const state = this._session.state;
    state.apply(reading.frame, { shared: verdict.shared });
    // A turn that is not telling a fact may still give a name ("hi i'm sarah"); a fact turn keeps
    // its words ("I'm allergic"), since the shared question must carry them.
    state.notePrivate([...(verdict.shared ? [] : privateWords(reading.text, reading.frame)), ...reading.names]);
    this._session.counts[verdict.route] += 1;
    const checked = reading.checkedAs(verdict);
    if (!verdict.shared) return new Checked(checked, new Verdict(CHECK_RULE, verdict.reasons.join(";"), [], null, verdict.route));
    if (this._session.replay) this._session.replay.remember(reading.text, verdict.question, reading.frame.questionType);
    return new Checked(checked);
  }

  _verdict(reading) {
    const state = this._session.state;
    let verdict = this._session.checker.check(reading.frame, reading.text, state);
    const chatTurn = new ChatTurn(reading.frame, reading.text, state);
    if (verdict.shared) {
      const objection = this._sharedQuestionRules.firstObjection(chatTurn);
      if (objection) verdict = new ChatVerdict(false, AGENT, [objection.reason]);
    }
    if (verdict.route !== URGENT && reading.aboutCaller) {
      const objection = this._urgentWords.check(chatTurn);
      if (objection) verdict = new ChatVerdict(false, objection.route, [objection.reason]); // never left to the model alone
    }
    return verdict;
  }
}

module.exports = { ChatQuestionCheck };
