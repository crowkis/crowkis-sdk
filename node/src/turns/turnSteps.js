"use strict";

// The parts TurnCore's fixed steps call: one small interface per step, each with a voice and a chat
// implementation that the facades (the composition roots) pick. JSDoc only: Node has no Protocol.
// A step marked "or a promise" answers at once unless it has to wait (a plugged-in model, a server
// read); TurnCore awaits only a promise, so a turn that waits for nothing keeps its timing.

/**
 * The call's settings a lookup reads, live: an app may change them between turns.
 * @typedef {object} CallSettings
 * @property {object} agent the agent lookups go through
 * @property {number} serveAbove the confidence a cached answer needs to be served
 * @property {number|null|undefined} latencyBudgetMs the lookup's budget (null: wait as long as the cache takes)
 */

/**
 * Which turn an answer belongs to (VoicePairing, ChatTurns).
 * @typedef {object} Pairing
 * @property {() => number} open a turn is being decided: its number
 * @property {(answered: object) => import("./checked.js").Checked} settle the answer paired with its
 *   turn, or the objection that drops it (the caller moved on)
 */

/**
 * Answers a turn gets without the cache or the model (VoiceReport, ChatAnswers).
 * @typedef {object} EarlyAnswers
 * @property {(said: string, turn: number) => object|null} beforeReading the channel's result for turn
 *   number `turn`, answered before it is read, or null
 * @property {(checked: import("./checked.js").Checked) => object|null|Promise<object|null>} afterCheck the
 *   channel's result for a turn the question check stopped and something other than the model answers
 *   (a filler, an app's hook), or null
 */

/**
 * How a turn is understood (VoiceReader, ChatReader).
 * @typedef {object} TurnReader
 * @property {(said: string, turn: number) => object|Promise<object>} read turn number `turn`, read: what
 *   the question and hit checks see
 */

/**
 * Stage 1: whether a turn may be looked up and shared (RuleSet, ChatQuestionCheck).
 * @typedef {object} QuestionCheck
 * @property {(turn: object) => import("./checked.js").Checked|Promise<import("./checked.js").Checked>} checkQuestion
 *   the turn as checked (keyed, for a chat) and the first objection, if any
 */

/**
 * Stage 2: whether a hit may be served (RuleSet, ChatHitCheck).
 * @typedef {object} HitCheck
 * @property {(turn: object, hit: object, started: number) => import("./checked.js").Checked} checkHit
 *   the hit as the hit rules read it and the objection to serving it, if any (it may still be pending)
 */

/**
 * Adapter: the channel's public results, counts and events for what the core found (VoiceReport, ChatReport).
 * @typedef {object} Report
 * @property {(checked: import("./checked.js").Checked) => object} toModel the question check stopped the
 *   turn: the model answers with the whole call
 * @property {(checked: import("./checked.js").Checked, looked: import("./checked.js").LookedUp) => object} missed
 *   no hit may be served: the model answers the turn
 * @property {(checked: import("./checked.js").Checked, looked: import("./checked.js").LookedUp) => object|Promise<object>} served
 *   a hit is served (`looked.cached`)
 * @property {(verdict: import("./verdict.js").Verdict) => any} kept an answer is not saved (dropped or
 *   kept out of the shared cache): the outcome
 * @property {(error: Error) => any} refused the write of an answer failed: the outcome
 * @property {(answered: object, outcome: any) => any} recorded whatever happened to an answer: counted or
 *   reported as the channel does; the outcome
 */

/**
 * Stage 3 and the write (VoiceSaving, ChatSaving).
 * @typedef {object} Saving
 * @property {(answered: object) => import("./checked.js").Checked|Promise<import("./checked.js").Checked>} check
 *   the answer as the save rules read it, and the objection to saving it, if any
 * @property {(answer: object) => Promise<any>} write share the answer and write it, within the bounded
 *   write: the outcome
 */

module.exports = {};
