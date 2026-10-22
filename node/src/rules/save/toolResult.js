"use strict";

// The ToolResult rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

const KEPT = "kept";

/** An answer built from a tool's result stays in the call. */
class ToolResult {
  get name() {
    return "ToolResult";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.private) return null;
    return new Verdict(this.name, "kept to this call: the answer was built from a tool's result", [COUNTER.NOT_SHAREABLE], KEPT);
  }
}

module.exports = { ToolResult };
