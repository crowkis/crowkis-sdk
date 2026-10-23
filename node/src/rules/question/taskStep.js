"use strict";

// The TaskStep rule (stage 1, question; Chat, V9).

const { Verdict } = require("../../turns/verdict.js");
const { TASK } = require("../../turns/routes.js");

/**
 * A step of a task in progress (booking, ordering, a reply to the agent's own question during one)
 * goes to the agent and is never shared.
 */
// A clock time ("8:45 PM", "9 am", "21:30"): while a task runs it is one of the task's own details.
const CLOCK_TIME = /\b\d{1,2}(:\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b|\b\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)(?!\w)/i;

class TaskStep {
  get name() {
    return "TaskStep";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.frame.taskStep || TaskStep._answersAgentDuringTask(turn) || TaskStep._namesATimeDuringTask(turn))) return null;
    return new Verdict(this.name, "V9_task_step", [], null, TASK);
  }

  /** While a task is running, a reply to the agent's own question is a step of it. */
  /**
   * While a task runs, a question naming a clock time is about the task ("Does the 8:45 PM flight have a
   * meal?" while a flight is being changed: v4, misfire C01), never a general question.
   */
  static _namesATimeDuringTask(turn) {
    return turn.state.task !== "none" && CLOCK_TIME.test(turn.text || "");
  }

  static _answersAgentDuringTask(turn) {
    const state = turn.state;
    return state.task !== "none" && state.lastReply.trimEnd().endsWith("?") && !String(turn.text || "").includes("?");
  }
}

module.exports = { TaskStep };
