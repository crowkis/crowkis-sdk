"use strict";

// The ChatToolResult rule (stage 3, save; Chat).

const { Verdict } = require("../../turns/verdict.js");

/**
 * Voice's ToolResult on Chat (v4): an answer the app built from a tool's result
 * (recordAnswer(..., { private: true })) stays in the chat.
 */
class ChatToolResult {
  get name() {
    return "ChatToolResult";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.private) return null;
    return new Verdict(this.name, "tool_result");
  }
}

module.exports = { ChatToolResult };
