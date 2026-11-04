"use strict";

const net = require("node:net");
const { resolveSettings } = require("./config.js");
const { CrowkisError, toBuffer, encode, RespReader, sleep, busyRetryMs, NO_SERVER_TOKEN } = require("./connection.js");

function imageBase64(value) {
  if (value === undefined || value === null) return null;
  return toBuffer(value).toString("base64");
}

function bufferToString(value) {
  if (value === undefined || value === null) return null;
  return Buffer.isBuffer(value) ? value.toString() : String(value);
}

/** A server reply with its buffers decoded, so it can be printed or compared. */
function plain(value) {
  if (Buffer.isBuffer(value)) return value.toString();
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, plain(item)]));
  }
  return value;
}

// The server refuses CMEMEXTRACT over 65,536 bytes or 64 facts, and finds at
// most one fact per sentence; a part stays well under both.
const EXTRACT_MAX_BYTES = 60 * 1024;
const EXTRACT_MAX_SENTENCES = 40;

// Sentence ends are the server's: . ! ? and new lines. A sentence over the byte
// cap is cut at character boundaries.
function extractParts(text) {
  const units = [];
  for (const sentence of String(text).split(/(?<=[\n.!?])/)) {
    if (Buffer.byteLength(sentence) < EXTRACT_MAX_BYTES) {
      units.push(sentence);
      continue;
    }
    let cut = "";
    let bytes = 0;
    for (const ch of sentence) {
      const size = Buffer.byteLength(ch);
      if (bytes + size >= EXTRACT_MAX_BYTES) {
        units.push(cut);
        cut = "";
        bytes = 0;
      }
      cut += ch;
      bytes += size;
    }
    if (cut) units.push(cut);
  }
  const parts = [];
  let part = "";
  let bytes = 0;
  let sentences = 0;
  for (const unit of units) {
    const size = Buffer.byteLength(unit);
    const counts = /[^\s.!?]/.test(unit);
    if (part && (bytes + size >= EXTRACT_MAX_BYTES || (counts && sentences >= EXTRACT_MAX_SENTENCES))) {
      parts.push(part);
      part = "";
      bytes = 0;
      sentences = 0;
    }
    part += unit;
    bytes += size;
    if (counts) sentences += 1;
  }
  if (part) parts.push(part);
  return parts;
}

const notStoredWarned = new Set();

// CSET answers `NOTSTORED <reason>` when it kept nothing; the caller still has
// its answer, so this is a warning, once per reason, never the answer itself.
// Returns false when it kept nothing.
function warnNotStored(reply) {
  if (typeof reply !== "string" || !reply.startsWith("NOTSTORED")) return true;
  const reason = reply.slice("NOTSTORED".length).trim();
  if (notStoredWarned.has(reason)) return false;
  notStoredWarned.add(reason);
  process.emitWarning(`crowkis: an answer was not cached: ${reason}`, "CrowkisWarning");
  return false;
}

// The spaces a cached answer is cut at, written out (not \s, which differs between Python and
// Node) so both SDKs cut it the same way: fixtures/stream-chunks.json.
const SPACES = "\\t\\n\\x0b\\x0c\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
// A word with the spacing after it, so the chunks of a cached answer join back to it exactly.
const WORD_WITH_SPACE = new RegExp(`[^${SPACES}]+[${SPACES}]*`, "g");
const LEADING_SPACE = new RegExp(`^[${SPACES}]*`);

function tokenChunks(text, chunkTokens = 4) {
  // A fraction is cut to a whole number, as Python's int() does.
  const size = Math.max(1, Math.min(Math.trunc(Number(chunkTokens) || 4), 128));
  text = String(text);
  const words = text.match(WORD_WITH_SPACE) || [];
  if (words.length) words[0] = LEADING_SPACE.exec(text)[0] + words[0];
  const chunks = [];
  for (let i = 0; i < words.length; i += size) {
    chunks.push(words.slice(i, i + size).join(""));
  }
  return chunks;
}

async function* streamValues(value) {
  value = await value;
  if (Buffer.isBuffer(value) || value instanceof Uint8Array || typeof value === "string") {
    yield value;
    return;
  }
  if (value && typeof value[Symbol.asyncIterator] === "function") {
    for await (const chunk of value) yield chunk;
    return;
  }
  if (value && typeof value[Symbol.iterator] === "function") {
    for (const chunk of value) yield chunk;
    return;
  }
  yield value;
}

class CrowkisClient {
  constructor(options = {}) {
    // Not passed here: CROWKIS_HOST / _PORT / _AUTH_TOKEN / _TENANT / _URL, then
    // 127.0.0.1:6383 with no token or tenant (see config.js).
    const settings = resolveSettings({
      host: options.host,
      port: options.port,
      authToken: options.authToken || options.auth_token || options.token,
      tenant: options.tenant,
    });
    this.host = settings.host;
    this.port = settings.port;
    this.tenant = settings.tenant;
    this.model = options.model;
    // Not enumerable: logging or JSON.stringify of a client must not print it.
    Object.defineProperty(this, "authToken", {
      value: settings.authToken,
      enumerable: false,
      writable: true,
    });
    this.timeoutMs = options.timeoutMs || 5000;
    this.maxRetries = Math.max(0, options.maxRetries ?? 2);
    this.backoffBaseMs = Math.max(0, options.backoffBaseMs ?? 100);
    this.socket = null;
    this.reader = null;
    this.resp3 = false;
    this._connecting = null; // the connection attempt in progress, shared by every caller
    this._closing = false; // close() was called while connecting: drop that connection
    this._busy = 0; // commands in flight: the socket keeps the process alive only then
  }

  connect() {
    // Calls that arrive together share one attempt, until it has finished (AUTH included):
    // each used to open its own socket, and every one but the last was never closed.
    if (this._connecting) return this._connecting;
    if (this.socket) return Promise.resolve();
    this._closing = false;
    this._connecting = this._open().finally(() => {
      this._connecting = null;
      // Opened by connect() alone, with nothing to send: idle until the first command.
      if (this.socket && !this._busy) this.socket.unref();
    });
    return this._connecting;
  }

  _open() {
    return new Promise((resolve, reject) => {
      const socket = net.createConnection({ host: this.host, port: this.port });
      const timer = setTimeout(() => {
        socket.destroy();
        reject(new CrowkisError("connect timeout"));
      }, this.timeoutMs);
      socket.once("connect", () => {
        clearTimeout(timer);
        if (this._closing) {
          // close() was called while this connection was being made: it is not used.
          socket.destroy();
          reject(new CrowkisError("connection closed"));
          return;
        }
        this.socket = socket;
        this.reader = new RespReader(socket);
        if (!this.authToken) {
          resolve();
          return;
        }
        socket.write(encode(["AUTH", this.authToken]));
        // A refused AUTH must not leave an unauthenticated socket behind for
        // the next command to use.
        this.reader.read().then(resolve, (error) => {
          this.close();
          reject(NO_SERVER_TOKEN.test(error.message)
            ? new CrowkisError("the server has no CROWKIS_AUTH_TOKEN set; remove authToken or set the same token on the server")
            : error);
        });
      });
      socket.once("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  // A server that accepts and never answers must not hold a caller forever.
  // The socket is dropped on timeout so a late reply cannot be read as the
  // answer to the next command.
  _readWithin(ms) {
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => {
        this.close();
        reject(new CrowkisError("read timeout"));
      }, ms);
    });
    return Promise.race([this.reader.read(), timeout]).finally(() => clearTimeout(timer));
  }

  close() {
    if (this._connecting) this._closing = true;
    if (this.socket) {
      this.socket.destroy();
      this.socket = null;
      this.reader = null;
      this.resp3 = false;
    }
  }

  async execute(...args) {
    // While a command is in flight the socket keeps the process alive; once nothing is,
    // it no longer does, so a script that never calls close() still exits.
    this._busy += 1;
    try {
      return await this._execute(args);
    } finally {
      this._busy -= 1;
      if (this._busy === 0 && this.socket) this.socket.unref();
    }
  }

  async _execute(args) {
    // Retry connection-level failures with exponential backoff +
    // jitter. RESP-level errors (CrowkisError from a live reply) are
    // NOT retried — the server answered; retrying a rejected command
    // is wrong. The exception is BUSY, which the server asks to be retried.
    let attempt = 0;
    for (;;) {
      try {
        await this.connect();
        this.socket.ref();
        this.socket.write(encode(args));
        return await this._readWithin(this.timeoutMs);
      } catch (error) {
        if (this.reader && this.reader.broken) this.close();
        const busyMs = busyRetryMs(error);
        if (busyMs !== null && attempt < this.maxRetries) {
          await new Promise((r) => setTimeout(r, busyMs));
          attempt += 1;
          continue;
        }
        const connectionLevel =
          busyMs === null && (
          error.code === "ECONNREFUSED" ||
          error.code === "ECONNRESET" ||
          error.code === "EPIPE" ||
          error.code === "ETIMEDOUT" ||
          (error instanceof CrowkisError && /timeout|closed/i.test(error.message)));
        if (!connectionLevel || attempt >= this.maxRetries) {
          throw error;
        }
        this.close();
        const delay =
          this.backoffBaseMs * 2 ** attempt * (1 + Math.random() * 0.1);
        await new Promise((r) => setTimeout(r, delay));
        attempt += 1;
      }
    }
  }

  async _hello3() {
    if (!this.resp3) {
      await this.execute("HELLO", "3");
      this.resp3 = true;
    }
  }

  async ping() {
    const value = await this.execute("PING");
    return value === "PONG";
  }

  async get(key) {
    const value = await this.execute("GET", key);
    return Buffer.isBuffer(value) ? value : null;
  }

  async set(key, value, options = {}) {
    const args = ["SET", key, value];
    if (options.ttl !== undefined) args.push("EX", String(options.ttl));
    await this.execute(...args);
  }

  _tenant(options = {}) {
    return options.tenant || this.tenant;
  }

  _model(options = {}) {
    return options.model || this.model;
  }

  async cset(query, response, options = {}) {
    const args = ["CSET", query, response];
    // The server refuses EX 0; a ttl of 0 (or null) sends no EX, so its default lifetime applies.
    if (options.ttl != null && Number(options.ttl) !== 0) args.push("EX", String(options.ttl));
    if (this._tenant(options)) args.push("TENANT", this._tenant(options));
    if (this._model(options)) args.push("MODEL", this._model(options));
    if (options.modelVersion || options.model_version) {
      args.push("MODEL_VERSION", options.modelVersion || options.model_version);
    }
    const image = imageBase64(options.image);
    if (image) args.push("IMAGE", image);
    if (options.template) args.push("TEMPLATE");
    if (options.segment) args.push("SEGMENT", options.segment);
    return warnNotStored(await this.execute(...args));
  }

  _cgetArgs(query, options) {
    const args = ["CGET", query];
    if (options.threshold !== undefined) args.push("THRESHOLD", String(options.threshold));
    if (this._tenant(options)) args.push("TENANT", this._tenant(options));
    if (this._model(options)) args.push("MODEL", this._model(options));
    if (options.modelVersion || options.model_version) {
      args.push("MODEL_VERSION", options.modelVersion || options.model_version);
    }
    if (options.migrationMode || options.migration_mode) {
      args.push("MIGRATION_MODE", options.migrationMode || options.migration_mode);
    }
    const image = imageBase64(options.image);
    if (image) args.push("IMAGE", image);
    if (options.template) args.push("TEMPLATE");
    if (options.segment) args.push("SEGMENT", options.segment);
    return args;
  }

  async cget(query, options = {}) {
    const args = this._cgetArgs(query, options);
    const value = await this.execute(...args);
    if (value && typeof value === "object" && !Buffer.isBuffer(value)) return value.response || null;
    return Buffer.isBuffer(value) ? value : null;
  }

  async cgetHit(query, options = {}) {
    await this._hello3();
    const args = this._cgetArgs(query, options);
    const value = await this.execute(...args);
    if (!value || Buffer.isBuffer(value)) return null;
    return {
      response: value.response || Buffer.alloc(0),
      text: (value.response || Buffer.alloc(0)).toString(),
      similarity: Number(value.similarity || 0),
      ttlRemaining: Number(value.ttl || 0),
      matchedKey: value.key || Buffer.alloc(0),
      confidence: Number(value.confidence || 0),
      hitType: Buffer.isBuffer(value.hit_type) ? value.hit_type.toString() : String(value.hit_type || "unknown"),
      migrationPending: Boolean(value.migration_pending),
      migrationFromModelVersion: bufferToString(value.migration_from_model_version),
      migrationTargetModelVersion: bufferToString(value.migration_target_model_version),
      migrationCanaryId: bufferToString(value.migration_canary_id),
      migrationPlannedAt: value.migration_planned_at === undefined ? null : Number(value.migration_planned_at),
      // Set when the server's decision engine judged this answer. Without an
      // engine these stay at their defaults and nothing changes.
      judged: Boolean(value.judged),
      vouched: Boolean(value.vouched),
      lifetime: bufferToString(value.lifetime),
      commitment: Boolean(value.commitment),
    };
  }

  async csim(query, options = {}) {
    await this._hello3();
    const args = ["CSIM", query, "K", String(Math.max(1, options.k || 10))];
    if (this._tenant(options)) args.push("TENANT", this._tenant(options));
    const value = await this.execute(...args);
    return (value || [])
      .filter((item) => item && typeof item === "object" && !Buffer.isBuffer(item))
      .map((item) => ({ key: item.key || Buffer.alloc(0), similarity: Number(item.similarity || 0) }));
  }

  async cimgget(image, options = {}) {
    await this._hello3();
    const args = ["CIMGGET", imageBase64(image) || ""];
    if (options.threshold !== undefined) args.push("THRESHOLD", String(options.threshold));
    if (this._tenant(options)) args.push("TENANT", this._tenant(options));
    if (this._model(options)) args.push("MODEL", this._model(options));
    const value = await this.execute(...args);
    if (value && typeof value === "object" && !Buffer.isBuffer(value)) return value.response || null;
    return Buffer.isBuffer(value) ? value : null;
  }

  async cflush(options = {}) {
    const args = ["CFLUSH"];
    if (this._tenant(options)) args.push("TENANT", this._tenant(options));
    return Number(await this.execute(...args));
  }

  async cvecCount() {
    return Number(await this.execute("CVECCOUNT"));
  }

  async cembed(text) {
    await this._hello3();
    const value = await this.execute("CEMBED", text);
    return Array.isArray(value) ? value.map(Number) : [];
  }

  async creuse(query) {
    await this._hello3();
    return this.execute("CREUSE", query);
  }

  async cthink(query, cotTrace) {
    await this._hello3();
    return this.execute("CTHINK", query, cotTrace);
  }

  async cwhyevict(query, tenant) {
    await this._hello3();
    const args = ["CWHYEVICT", query];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async cstale(query, tenant, segment) {
    await this._hello3();
    const args = ["CSTALE", query];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    if (segment) args.push("SEGMENT", segment);
    return this.execute(...args);
  }

  async cinvalidate(instruction, { tenant, threshold, limit, commit } = {}) {
    await this._hello3();
    const args = ["CINVALIDATE", instruction];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    if (threshold !== undefined) args.push("THRESHOLD", String(threshold));
    if (limit !== undefined) args.push("LIMIT", String(limit));
    if (commit) args.push("COMMIT");
    return this.execute(...args);
  }

  /** What the server's decision engine concluded about a question. */
  async cdecision(query, { tenant } = {}) {
    await this._hello3();
    const args = ["CDECISION", query];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return plain(await this.execute(...args));
  }

  /**
   * Tell the cache something changed. Removes the cached answers the notice
   * makes wrong; with `lasts` (seconds) it stays active until then.
   */
  async cnoticeAdd(text, { lasts, preview, tenant } = {}) {
    await this._hello3();
    const args = ["CNOTICE", "ADD", text];
    if (lasts !== undefined && lasts !== null) args.push("EX", String(lasts));
    if (preview) args.push("PREVIEW");
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return plain(await this.execute(...args));
  }

  async cnoticeList({ tenant } = {}) {
    await this._hello3();
    const args = ["CNOTICE", "LIST"];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return plain(await this.execute(...args)) || [];
  }

  async cnoticeClear(noticeId, { tenant } = {}) {
    await this._hello3();
    const args = ["CNOTICE", "CLEAR", noticeId];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return Boolean(await this.execute(...args));
  }

  async cmemset(agent, fact, { user, ex, tenant } = {}) {
    await this._hello3();
    const args = ["CMEMSET", agent, fact];
    if (user) args.push("USER", user);
    if (ex !== undefined) args.push("EX", String(ex));
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  async cmemget(agent, query, { user, k, tenant } = {}) {
    await this._hello3();
    const args = ["CMEMGET", agent, query];
    if (user) args.push("USER", user);
    if (k !== undefined) args.push("K", String(k));
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  // Long text goes in parts, in order, under the server's caps; the facts each
  // part stored come back as one list. A refused part stops the rest.
  async cmemextract(agent, conversation, { user, ex, tenant } = {}) {
    await this._hello3();
    const options = [];
    if (user) options.push("USER", user);
    if (ex !== undefined) options.push("EX", String(ex));
    if (this._tenant({ tenant })) options.push("TENANT", this._tenant({ tenant }));
    const parts = extractParts(conversation);
    if (parts.length <= 1) return this.execute("CMEMEXTRACT", agent, conversation, ...options);
    const facts = [];
    for (const part of parts) {
      const stored = await this.execute("CMEMEXTRACT", agent, part, ...options);
      if (Array.isArray(stored)) facts.push(...stored);
    }
    return facts;
  }

  async cmemhistory(agent, query, { user, k, tenant } = {}) {
    await this._hello3();
    const args = ["CMEMHISTORY", agent, query];
    if (user) args.push("USER", user);
    if (k !== undefined) args.push("K", String(k));
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  async cmemasof(agent, query, unixMs, { user, k, tenant } = {}) {
    await this._hello3();
    const args = ["CMEMASOF", agent, query, String(unixMs)];
    if (user) args.push("USER", user);
    if (k !== undefined) args.push("K", String(k));
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  async cmemforget(agent, { query, user, threshold, tenant } = {}) {
    await this._hello3();
    // The query slot is always sent ("" = everything), as Python does, so an
    // option keyword can never land in it.
    const args = ["CMEMFORGET", agent, query || ""];
    if (user) args.push("USER", user);
    if (threshold !== undefined) args.push("THRESHOLD", String(threshold));
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  async cmemlink(agent, subject, relation, object, { user, tenant } = {}) {
    await this._hello3();
    const args = ["CMEMLINK", agent, subject, relation, object];
    if (user) args.push("USER", user);
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  async cmemgraph(agent, entity, { user, depth, tenant } = {}) {
    await this._hello3();
    const args = ["CMEMGRAPH", agent, entity];
    if (user) args.push("USER", user);
    if (depth !== undefined) args.push("DEPTH", String(depth));
    if (this._tenant({ tenant })) args.push("TENANT", this._tenant({ tenant }));
    return this.execute(...args);
  }

  async cdocAdd(docId, text, { tenant, ex } = {}) {
    await this._hello3();
    const args = ["CDOC", "ADD", docId, text];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    if (ex !== undefined) args.push("EX", String(ex));
    return this.execute(...args);
  }

  async cdocSearch(query, { k, tenant } = {}) {
    await this._hello3();
    const args = ["CDOC", "SEARCH", query];
    if (k !== undefined) args.push("K", String(k));
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async csessionAdd(session, role, text, { ex } = {}) {
    await this._hello3();
    const args = ["CSESSION", "ADD", session, role, text];
    if (ex !== undefined) args.push("EX", String(ex));
    return this.execute(...args);
  }

  async csessionRecent(session, { n } = {}) {
    await this._hello3();
    const args = ["CSESSION", "RECENT", session];
    if (n !== undefined) args.push("N", String(n));
    return this.execute(...args);
  }

  async csessionSearch(session, query, { k } = {}) {
    await this._hello3();
    const args = ["CSESSION", "SEARCH", session, query];
    if (k !== undefined) args.push("K", String(k));
    return this.execute(...args);
  }

  async cpin(query, answer, { by, tenant } = {}) {
    await this._hello3();
    const args = ["CPIN", query, answer];
    if (by) args.push("BY", by);
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async cpinget(query, { tenant, threshold } = {}) {
    await this._hello3();
    const args = ["CPINGET", query];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    if (threshold !== undefined) args.push("THRESHOLD", String(threshold));
    return this.execute(...args);
  }

  async cpinlist({ tenant } = {}) {
    await this._hello3();
    const args = ["CPINLIST"];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async cunpin(query, { tenant } = {}) {
    await this._hello3();
    const args = ["CUNPIN", query];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async ctoolset(tool, argsStr, result, { ex, tenant } = {}) {
    await this._hello3();
    const args = ["CTOOLSET", tool, argsStr, result];
    if (ex !== undefined) args.push("EX", String(ex));
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async ctoolget(tool, argsStr, { tenant } = {}) {
    await this._hello3();
    const args = ["CTOOLGET", tool, argsStr];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  /** Store a spoken answer (Voice add-on): raw audio for this answer in this voice, language, speed and format. */
  async caudioset(answer, voice, language, speed, audioFormat, audio, { ex, ms, tenant } = {}) {
    await this._hello3();
    const args = ["CAUDIOSET", answer, voice, language, String(speed), audioFormat, Buffer.from(audio)];
    if (ex !== undefined && ex !== null) args.push("EX", String(ex));
    if (ms !== undefined && ms !== null) args.push("MS", String(ms));
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  /** The stored audio for this answer, voice, language, speed and format, or null (Voice add-on). */
  async caudioget(answer, voice, language, speed, audioFormat, { tenant } = {}) {
    await this._hello3();
    const args = ["CAUDIOGET", answer, voice, language, String(speed), audioFormat];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    const value = await this.execute(...args);
    if (value === null || value === undefined) return null;
    return Buffer.isBuffer(value) ? value : Buffer.from(String(value));
  }

  /** Add a voice bot's counts to the Voice page (Voice add-on): whole numbers by name. */
  async cvoicestat(counts, { tenant } = {}) {
    await this._hello3();
    const args = ["CVOICESTAT"];
    for (const [name, count] of Object.entries(counts)) args.push(name, String(Math.trunc(count)));
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async cflag(query, badAnswer, { reason, tenant } = {}) {
    await this._hello3();
    const args = ["CFLAG", query, badAnswer];
    if (reason) args.push("REASON", reason);
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async ccheckbad(query, { tenant, threshold } = {}) {
    await this._hello3();
    const args = ["CCHECKBAD", query];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    if (threshold !== undefined) args.push("THRESHOLD", String(threshold));
    return this.execute(...args);
  }

  async cguard(text) {
    await this._hello3();
    return this.execute("CGUARD", text);
  }

  async coutcheck(text) {
    await this._hello3();
    return this.execute("COUTCHECK", text);
  }

  // ── Phase 0.1 operator surface ─────────────────────────────────────

  async cinfo(section) {
    const args = section ? ["CINFO", section] : ["CINFO"];
    const value = await this.execute(...args);
    return value == null ? "" : value.toString();
  }

  async cbudgetGet(tenant) {
    await this._hello3();
    return this.execute("CBUDGET", "GET", tenant || this.tenant || "default");
  }

  async cbudgetAlerts() {
    await this._hello3();
    return this.execute("CBUDGET", "ALERTS");
  }

  // Set a tenant's spend budget. The gateway enforces it: cost-aware routing
  // past the alert %, and a hard block on upstream calls past the circuit %.
  async cbudgetSet(tenant, { dailyUsd, monthlyUsd, costPer1k, alertPct, circuitPct } = {}) {
    await this._hello3();
    const args = ["CBUDGET", "SET", tenant || this.tenant || "default"];
    if (dailyUsd != null) args.push("DAILY", String(dailyUsd));
    if (monthlyUsd != null) args.push("MONTHLY", String(monthlyUsd));
    if (costPer1k != null) args.push("COST", String(costPer1k));
    if (alertPct != null) args.push("ALERT", String(alertPct));
    if (circuitPct != null) args.push("CIRCUIT", String(circuitPct));
    return this.execute(...args);
  }

  // Zero a tenant's spend counters; the limits stay. Replies with the budget.
  async cbudgetReset(tenant) {
    await this._hello3();
    return this.execute("CBUDGET", "RESET", tenant || this.tenant || "default");
  }

  async cdedup(tenant) {
    await this._hello3();
    const args = ["CDEDUP"];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  async cpiiReport(tenant) {
    await this._hello3();
    const args = ["CPII", "REPORT"];
    const t = tenant || this.tenant;
    if (t) args.push("TENANT", t);
    return this.execute(...args);
  }

  // A preview unless `commit` is set: the reply counts what would go and
  // nothing is deleted. The scope is explicit — a tenant, or `allTenants`.
  async cpiiErase(identifier, tenant, { commit = false, allTenants = false } = {}) {
    await this._hello3();
    const args = ["CPII", "ERASE", identifier];
    const t = allTenants ? null : tenant || this.tenant;
    if (t) args.push("TENANT", t);
    else args.push("ALL");
    if (commit) args.push("COMMIT");
    return this.execute(...args);
  }

  async csave(dest) {
    return (await this.execute("CSAVE", dest)) === "OK";
  }

  async cbgsave(dest) {
    return (await this.execute("CBGSAVE", dest)) === "BGSAVE-STARTED";
  }

  async creload() {
    await this._hello3();
    return this.execute("CRELOAD");
  }

  async ckeylimitSet(tenant, { rpm, tpm } = {}) {
    const args = ["CKEYLIMIT", "SET", tenant, "RPM", String(rpm)];
    if (tpm != null) args.push("TPM", String(tpm));
    return (await this.execute(...args)) === "OK";
  }

  async ckeylimitGet(tenant) {
    await this._hello3();
    return this.execute("CKEYLIMIT", "GET", tenant);
  }

  async ckeylimitDel(tenant) {
    return Number(await this.execute("CKEYLIMIT", "DEL", tenant)) === 1;
  }

  // ── freshness sources, evals, prompt versioning, scan, compaction ───────

  async cscan(cursor = "0", options = {}) {
    const args = ["CSCAN", String(cursor)];
    if (options.match) args.push("MATCH", options.match);
    if (options.count != null) args.push("COUNT", String(options.count));
    if (options.intent) args.push("INTENT", options.intent);
    if (this._tenant(options)) args.push("TENANT", this._tenant(options));
    const value = await this.execute(...args);
    if (Array.isArray(value) && value.length === 2) {
      const next = Buffer.isBuffer(value[0]) ? value[0].toString() : String(value[0]);
      return { cursor: next, keys: value[1] || [] };
    }
    return { cursor: "0", keys: [] };
  }

  async ceval(evaluator, input, output, options = {}) {
    const args = ["CEVAL", evaluator, input, output];
    if (options.expect != null) args.push("EXPECT", options.expect);
    if (options.threshold != null) args.push("THRESHOLD", String(options.threshold));
    return this.execute(...args);
  }

  async cpromptSet(name, template) {
    return Number(await this.execute("CPROMPT", "SET", name, template));
  }

  async cpromptGet(name, version) {
    const args = ["CPROMPT", "GET", name];
    if (version != null) args.push(String(version));
    const v = await this.execute(...args);
    return Buffer.isBuffer(v) ? v : null;
  }

  async cpromptList() {
    return this.execute("CPROMPT", "LIST");
  }

  async cpromptVersions(name) {
    return this.execute("CPROMPT", "VERSIONS", name);
  }

  // The prompt commands below send TENANT only when it is passed: cpromptSet
  // and cpromptGet send none, so a client-wide tenant would point a delete or
  // render at a different prompt from the one they wrote.
  async cpromptDel(name, { tenant } = {}) {
    const args = ["CPROMPT", "DEL", name];
    if (tenant) args.push("TENANT", tenant);
    return Number(await this.execute(...args)) === 1;
  }

  // Makes `version` the active one; replies with it.
  async cpromptRollback(name, version, { tenant } = {}) {
    const args = ["CPROMPT", "ROLLBACK", name, String(version)];
    if (tenant) args.push("TENANT", tenant);
    return Number(await this.execute(...args));
  }

  // The template with each {{key}} replaced from `vars`; null if there is none.
  async cpromptRender(name, { version, vars, tenant } = {}) {
    const args = ["CPROMPT", "RENDER", name];
    if (version != null) args.push(String(version));
    if (tenant) args.push("TENANT", tenant);
    const pairs = Object.entries(vars || {});
    if (pairs.length > 0) {
      args.push("VARS");
      for (const [key, value] of pairs) {
        // The server splits each token at its first "=" and stops at the first bad one.
        if (!key || key.includes("=")) throw new Error(`prompt var name must be non-empty and contain no "=": ${JSON.stringify(key)}`);
        args.push(`${key}=${value}`);
      }
    }
    const value = await this.execute(...args);
    return Buffer.isBuffer(value) ? value : null;
  }

  // The A/B pick for `subject` (sticky per subject): { version, template } or null.
  async cpromptAb(name, { subject, tenant } = {}) {
    const args = ["CPROMPT", "AB", name];
    if (tenant) args.push("TENANT", tenant);
    if (subject != null) args.push("SUBJECT", String(subject));
    const value = await this.execute(...args);
    if (!Array.isArray(value) || value.length !== 2 || !Buffer.isBuffer(value[1])) return null;
    return { version: Number(value[0]), template: value[1] };
  }

  // Set the A/B split as { version: weight }; no weights clears it.
  async cpromptAbset(name, weights, { tenant } = {}) {
    const args = ["CPROMPT", "ABSET", name];
    const pairs = weights instanceof Map ? [...weights] : Object.entries(weights || {});
    for (const [version, weight] of pairs) {
      // The server stops reading pairs at the first value that is not a u32,
      // which would silently drop the rest of the split.
      for (const n of [version, weight]) {
        if (!/^\d+$/.test(String(n)) || Number(n) > 0xFFFFFFFF) {
          throw new Error(`A/B versions and weights must be whole numbers: ${JSON.stringify(n)}`);
        }
      }
      args.push(String(version), String(weight));
    }
    if (tenant) args.push("TENANT", tenant);
    return (await this.execute(...args)) === "OK";
  }

  async csourceLink(sourceId, query, options = {}) {
    const args = ["CSOURCE", "LINK", sourceId, query];
    const tenant = options.tenant || this.tenant;
    if (tenant) args.push("TENANT", tenant);
    return String(await this.execute(...args)) === "OK";
  }

  async csourcePurge(sourceId) {
    return Number(await this.execute("CSOURCE", "PURGE", sourceId));
  }

  async csourceList(sourceId) {
    return this.execute("CSOURCE", "LIST", sourceId);
  }

  async compact() {
    return this.execute("COMPACT");
  }

  // Storage-engine counters (memtable, levels, block cache, refused embeddings).
  async stats() {
    await this._hello3();
    const value = await this.execute("STATS");
    return value && typeof value === "object" && !Buffer.isBuffer(value) && !Array.isArray(value) ? value : {};
  }

  // Remove expired keys now; replies with how many went.
  async sweep() {
    return Number(await this.execute("SWEEP"));
  }

  async getOrCompute(query, fn, options = {}) {
    const cached = await this.cget(query, options);
    if (cached) return cached.toString();
    const response = await fn(query);
    const bytes = toBuffer(response);
    await this.cset(query, bytes, options);
    return bytes.toString();
  }

  async *streamGetOrCompute(query, fn, options = {}) {
    const cached = await this.cget(query, options);
    if (cached) {
      for (const chunk of tokenChunks(cached.toString(), options.chunkTokens || 4)) {
        yield chunk;
        if ((options.delayMs || 20) > 0) await sleep(options.delayMs || 20);
      }
      return;
    }

    const chunks = [];
    let completed = false;
    try {
      for await (const chunk of streamValues(fn(query))) {
        chunks.push(toBuffer(chunk));
        yield chunk;
      }
      completed = true;
    } finally {
      if (completed) {
        await this.cset(query, Buffer.concat(chunks), options);
      }
    }
  }

  // ── High-level, model-agnostic cache API (clean names) ──────────────────
  // Works with ANY model or provider. Bring the call; Crowkis caches by meaning.

  async lookup(prompt, options = {}) {
    // Semantic read → { text, similarity, confidence } or null.
    return this.cgetHit(prompt, options);
  }

  async store(prompt, answer, options = {}) {
    // Cache an answer for a prompt (options.ttl in seconds).
    return this.cset(prompt, answer, options);
  }

  async ask(prompt, compute, options = {}) {
    // Recall the answer, else run compute(prompt) — any model — cache it, return it.
    return this.getOrCompute(prompt, compute, options);
  }

  cached(fn, options = {}) {
    // Wrap ANY async function whose first arg is the prompt in a semantic cache.
    // Model-agnostic — fn can call any provider.
    const self = this;
    return async function (prompt, ...rest) {
      const hit = await self.cget(prompt, options);
      if (hit) return hit.toString();
      const out = await fn(prompt, ...rest);
      await self.cset(prompt, toBuffer(out), options);
      return typeof out === "string" ? out : toBuffer(out).toString();
    };
  }

  stream(prompt, compute, options = {}) {
    // Streamed recall-or-compute (async iterator of chunks).
    return this.streamGetOrCompute(prompt, compute, options);
  }

  async similar(prompt, options = {}) {
    return this.csim(prompt, options);
  }

  async embed(text) {
    return this.cembed(text);
  }

  async flush(options = {}) {
    return this.cflush(options);
  }
}

module.exports = { CrowkisClient };
