"use strict";

// Chat: cache a chat app's answers safely, in a few lines. Mirrors crowkis/chat.py.
//
//   const chat = new Chat(agent, new LLMUnderstander(complete), { system: "You are Acme's assistant." });
//   const reply = await chat.turn("thread-42", messages, myModel);   // messages: the whole chat
//
// Each user turn becomes one stand-alone question that carries what the user said earlier
// ("Is pad thai safe for someone with a peanut allergy?"). Fixed rules check it; it is looked
// up, and on a miss the model answers that question alone (with `system`) and the answer is
// saved for every user. Anything personal, urgent, part of a booking or unclear is answered
// with the whole chat and never cached. Per thread only a small memory is kept in `store`.

const { CallSession, _masked: masked } = require("./session.js");
const { TurnFrame } = require("./turn.js");
const { normalise } = require("./understand.js");
const { RuleChecker, SHARED } = require("./verify.js");

class ChatConflict extends Error {
  constructor(message) {
    super(message);
    this.name = "ChatConflict";
  }
}

/** Threads' memory in this process, with a version per thread; the oldest past `maxThreads` are forgotten. */
class MemoryStore {
  constructor({ maxThreads = 100000 } = {}) {
    this._data = new Map();
    this.maxThreads = maxThreads;
  }

  load(threadId) {
    const entry = this._data.get(threadId);
    return entry ? [entry[0], entry[1]] : [null, 0];
  }

  /** Store `data` if the thread is still at `version`; false if it moved on. */
  save(threadId, data, version) {
    const current = this._data.has(threadId) ? this._data.get(threadId)[1] : 0;
    if (current !== version) return false;
    this._data.delete(threadId);
    this._data.set(threadId, [data, version + 1]);
    while (this._data.size > this.maxThreads) this._data.delete(this._data.keys().next().value);
    return true;
  }

  delete(threadId) {
    this._data.delete(threadId);
  }
}

// A message's text: a string, or the text parts of a list of parts (OpenAI style).
function content(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .filter((p) => typeof p === "string" || (p && typeof p === "object" && (p.type ?? "text") === "text"))
      .map((p) => (typeof p === "string" ? p : String(p.text ?? "")))
      .join(" ");
  }
  return value === null || value === undefined ? "" : String(value);
}

// The thread's memory holds nothing that can change an answer: no fact, detail, region or tier,
// reply language or task.
const settled = (state) => !(state.facts.length || state.stated.length || state.details.length ||
  Object.keys(state.attributes).length || state.language || state.task !== "none");

// Reads a turn without a model call when the model already read it: word for word a question that
// an earlier turn asked on its own (not rewritten, not leaning on its chat), in a thread whose memory
// could not change it, and that the rules shared. The rules still check every turn. In this process
// only, at most `maxQuestions`.
class Repeats {
  constructor(understander, maxQuestions = 10000) {
    this.understander = understander;
    this.maxQuestions = maxQuestions;
    this._known = new Map();
  }

  understand(turn, state) {
    const frame = settled(state) ? this._known.get(normalise(turn)) : undefined;
    return frame !== undefined ? frame : this.understander.understand(turn, state);
  }

  remember(turn, wasSettled, result) {
    const { frame, verdict } = result;
    if (!wasSettled || result.route !== SHARED || !frame || !verdict || frame.usesState) return;
    const key = normalise(turn);
    if (!key || key !== normalise(verdict.question || "")) return;
    // A region or tier comes from the thread that asked; the next thread's own memory gives its own.
    this._known.delete(key);
    this._known.set(key, new TurnFrame({ ...frame, attributes: {} }));
    while (this._known.size > this.maxQuestions) this._known.delete(this._known.keys().next().value);
  }
}

class Chat {
  /**
   * @param agent        a crowkis Agent
   * @param understander turns a turn into a frame (an LLMUnderstander over any model)
   * @param options      store, system (the business's instructions for shared answers), channel,
   *                     knowledgeVersion, and CallSession options (urgentReply, onTools, fillers...)
   */
  constructor(agent, understander, options = {}) {
    const { store = null, system = "", channel = "chat", knowledgeVersion = "1", ...sessionOptions } = options;
    this.agent = agent;
    this.understander = understander;
    this._repeats = new Repeats(understander);
    this.store = store || new MemoryStore();
    this.system = String(system || "").trim();
    if (!sessionOptions.checker) sessionOptions.checker = new RuleChecker({ channel, knowledgeVersion });
    // A chat waits for its model anyway: understanding gets seconds, not a voice turn's 250 ms.
    if (sessionOptions.understandBudgetMs === undefined) sessionOptions.understandBudgetMs = 10000;
    this.sessionOptions = sessionOptions;
    // One turn at a time per thread in this process. A thread's queue exists only while one of its
    // turns runs, so unrelated chats never wait on each other.
    this._queues = new Map();
  }

  /**
   * Answer the last user message of `messages` (the whole chat, OpenAI style). `answer` is the
   * app's model: it gets chat messages and returns the reply text. Rejects with ChatConflict when
   * another request answered this thread at the same time.
   */
  turn(threadId, messages, answer) {
    threadId = String(threadId);
    const previous = this._queues.get(threadId) || Promise.resolve();
    const run = previous.then(() => this._turn(threadId, messages, answer));
    const tail = run.catch(() => {});
    this._queues.set(threadId, tail);
    tail.then(() => { if (this._queues.get(threadId) === tail) this._queues.delete(threadId); });
    return run;
  }

  /** Erase a thread's memory (a user's right to erasure). Its shared answers hold nothing of it. */
  async forget(threadId) {
    if (typeof this.store.delete !== "function") throw new TypeError("this store cannot delete; give it a delete(threadId) method");
    await this.store.delete(String(threadId));
  }

  async _turn(threadId, messages, answer) {
    const user = [...(messages || [])].reverse().find((m) => m && typeof m === "object" && m.role === "user");
    const text = user ? content(user.content) : "";
    const [data, version] = await this.store.load(threadId);
    const session = CallSession.restore(this.agent, this._repeats, data, this.sessionOptions);
    const wasSettled = settled(session.state);
    const result = await session.handle(text);
    this._repeats.remember(text, wasSettled, result);
    let reply;
    let outcome;
    if (!result.needsModel && result.text !== null) {
      reply = result.text;
      outcome = "served";
    } else {
      const asked = result.messages === null
        ? [...(messages || [])] // personal or unclear: the whole chat, never cached
        : [...(this.system ? [{ role: "system", content: this.system }] : []), ...result.messages];
      reply = await answer(asked);
      outcome = await session.recordAnswer(result, reply);
      if (outcome === "refused:non_answer" && result.messages !== null) {
        // The question alone did not carry enough ("What were the steps again?"): the user is answered
        // from the whole chat instead, and nothing is saved.
        reply = await answer([...(messages || [])]);
        session.state.noteAgentReply(masked(reply)); // what the user saw, names masked
      }
    }
    if (!(await this.store.save(threadId, session.export(), version))) {
      throw new ChatConflict(`thread ${threadId} was answered by another request at the same time`);
    }
    return { text: reply, route: result.route, fromCache: result.servedFromCache, outcome, reason: result.reason || "" };
  }
}

module.exports = { Chat, ChatConflict, MemoryStore };
