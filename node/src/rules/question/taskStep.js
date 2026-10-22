"use strict";

// The TaskStep rule (stage 1, question; Chat, V9).

const { Verdict } = require("../../turns/verdict.js");
const { TASK } = require("../../turns/routes.js");

/**
 * A step of a task in progress (booking, ordering, a reply to the agent's own question during one)
 * goes to the agent and is never shared.
 */
class TaskStep {
  get name() {
    return "TaskStep";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.frame.taskStep || TaskStep._answersAgentDuringTask(turn))) return null;
    return new Verdict(this.name, "V9_task_step", [], null, TASK);
  }

  /** While a task is running, a reply to the agent's own question is a step of it. */
  static _answersAgentDuringTask(turn) {
    const state = turn.state;
    return state.task !== "none" && state.lastReply.trimEnd().endsWith("?") && !String(turn.text || "").includes("?");
  }
}

module.exports = { TaskStep };
