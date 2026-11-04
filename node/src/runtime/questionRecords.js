"use strict";

const crypto = require("node:crypto");
const { LATE, within } = require("./deadline.js");
const { differentSpecifics } = require("../understanding/wordRules/answers.js");
const { QUESTIONS_KEPT, QUESTION_TTL } = require("../understanding/wordRules/phrases.js");

/** Where an answer's questions are kept: by the tenant and a hash of the answer. */
function questionKey(tenant, answer) {
  const trimmed = String(answer).replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, ""); // as Python's strip(" \t\r\n")
  const digest = crypto.createHash("sha256").update(trimmed, "utf8").digest("hex").slice(0, 32);
  return `crowkis:question:${tenant || "default"}:${digest}`;
}

const tenantOf = (agent) => (agent && (agent.tenant || (agent.client && agent.client.tenant))) || null;

/**
 * The questions each shared answer was saved for, kept next to the answer on the server, so a later
 * near hit can be checked against them (DifferentQuestion). Best effort on both sides: a record that
 * could not be written only means a later hit cannot be checked, and one that cannot be read in time
 * means "not a different question", as before the record existed. `track` is told of each record
 * still being written (so tests and shutdown can wait for them).
 */
class QuestionRecords {
  constructor(agent, { track = () => {} } = {}) {
    this._agent = agent;
    this._track = track;
  }

  /** Note, in the background, that `answer` was saved for `question`. */
  keep(question, answer, ttl = null) {
    const client = this._agent && this._agent.client;
    if (!client || typeof client.set !== "function") return;
    const key = questionKey(tenantOf(this._agent), answer);
    const record = (async () => {
      try {
        const raw = await client.get(key);
        let kept = raw ? JSON.parse(String(raw)) : [];
        kept = (Array.isArray(kept) ? kept : []).filter((q) => typeof q === "string" && q !== question).slice(-(QUESTIONS_KEPT - 1));
        await client.set(key, JSON.stringify([...kept, question]), { ttl: ttl || QUESTION_TTL });
      } catch {
        // see the class comment
      }
    })(); // never on the audio-clip queue
    this._track(record);
  }

  /**
   * Whether every question `answer` was saved for asks about something else, read within `waitMs`
   * (null: as long as the server takes). Unknown means no.
   */
  async answersAnotherQuestion(asked, answer, waitMs) {
    const client = this._agent && this._agent.client;
    if (!client || typeof client.get !== "function") return false;
    try {
      const read = Promise.resolve().then(() => client.get(questionKey(tenantOf(this._agent), answer)));
      read.catch(() => {});
      if (waitMs !== null && waitMs <= 0) return false;
      const raw = waitMs === null ? await read : await within(waitMs, read);
      if (raw === LATE || !raw) return false;
      const questions = JSON.parse(String(raw));
      if (!Array.isArray(questions)) return false;
      const kept = questions.filter((q) => typeof q === "string");
      return kept.length > 0 && kept.every((q) => differentSpecifics(asked, q));
    } catch {
      return false;
    }
  }
}

module.exports = { QuestionRecords, questionKey, tenantOf };
