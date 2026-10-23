"use strict";

// The ChatCallerIdentifier rule (stage 3, save; Chat).

const { Verdict } = require("../../turns/verdict.js");
const { identifiers } = require("../../understanding/wordRules/index.js");

/**
 * Voice's CallerIdentifier on Chat (v4): an answer repeating an ID-like value the user said anywhere in
 * this chat (an order number, an email, a long digit group), even in a turn that was shared, is never
 * shared, unless the shared question itself has it.
 */
class ChatCallerIdentifier {
  get name() {
    return "ChatCallerIdentifier";
  }

  get floor() {
    return false;
  }

  check(answer) {
    const asked = identifiers([answer.verdict.question || ""]);
    if (![...identifiers([answer.text])].some((value) => !asked.has(value) && answer.state.saidIdentifier(value))) return null;
    return new Verdict(this.name, "caller_identifier");
  }
}

module.exports = { ChatCallerIdentifier };
