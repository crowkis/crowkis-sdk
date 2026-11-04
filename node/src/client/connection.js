"use strict";

// The RESP wire: the error type, the encoder, the reader and the retry timing.

class CrowkisError extends Error {
  constructor(message) {
    super(message);
    this.name = "CrowkisError";
  }
}

function toBuffer(value) {
  if (Buffer.isBuffer(value)) return value;
  if (value instanceof Uint8Array) return Buffer.from(value);
  return Buffer.from(String(value));
}

function encode(args) {
  const parts = [Buffer.from(`*${args.length}\r\n`)];
  for (const arg of args.map(toBuffer)) {
    parts.push(Buffer.from(`$${arg.length}\r\n`), arg, Buffer.from("\r\n"));
  }
  return Buffer.concat(parts);
}

class RespReader {
  constructor(socket) {
    this.socket = socket;
    this.buffer = Buffer.alloc(0);
    this.waiters = [];
    socket.on("data", (chunk) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      this._drain();
    });
    socket.on("error", (error) => this._reject(error));
    socket.on("close", () => this._reject(new CrowkisError("connection closed")));
  }

  async read() {
    return this._parseOrWait();
  }

  _parseOrWait() {
    const parsed = this._parse();
    if (parsed) {
      this.buffer = this.buffer.subarray(parsed.offset);
      return parsed.error ? Promise.reject(parsed.error) : Promise.resolve(parsed.value);
    }
    return new Promise((resolve, reject) => this.waiters.push({ resolve, reject }));
  }

  // Runs inside the socket's "data" listener, so nothing here may throw: an
  // exception there is uncaught and takes down every call on the process.
  _drain() {
    while (this.waiters.length > 0) {
      const parsed = this._parse();
      if (!parsed) return;
      this.buffer = this.buffer.subarray(parsed.offset);
      const waiter = this.waiters.shift();
      if (parsed.error) waiter.reject(parsed.error);
      else waiter.resolve(parsed.value);
    }
  }

  // A frame of an unknown type cannot be skipped, so nothing after it on this
  // socket can be read: that call gets the error and the socket is dropped
  // (`broken` tells the client to reconnect on the next call).
  _parse() {
    try {
      return this._parseValue(0);
    } catch (error) {
      this.broken = true;
      this.socket.destroy();
      return { error, offset: this.buffer.length };
    }
  }

  _reject(error) {
    while (this.waiters.length > 0) {
      this.waiters.shift().reject(error);
    }
  }

  _line(offset) {
    const end = this.buffer.indexOf("\r\n", offset);
    if (end < 0) return null;
    return {
      line: this.buffer.subarray(offset, end),
      offset: end + 2,
    };
  }

  _parseValue(offset) {
    const first = this.buffer[offset];
    if (first === undefined) return null;
    const line = this._line(offset);
    if (!line) return null;
    const payload = line.line.subarray(1);
    const text = payload.toString();

    switch (String.fromCharCode(first)) {
      case "+":
        return { value: text, offset: line.offset };
      case "-":
        return { error: new CrowkisError(text), offset: line.offset };
      case ":":
        return { value: Number.parseInt(text, 10), offset: line.offset };
      case ",":
        return { value: Number.parseFloat(text), offset: line.offset };
      case "_":
        return { value: null, offset: line.offset };
      case "#":
        return { value: text === "t", offset: line.offset };
      case "$": {
        const len = Number.parseInt(text, 10);
        if (len < 0) return { value: null, offset: line.offset };
        const end = line.offset + len + 2;
        if (this.buffer.length < end) return null;
        return {
          value: this.buffer.subarray(line.offset, line.offset + len),
          offset: end,
        };
      }
      case "*": {
        const count = Number.parseInt(text, 10);
        if (count < 0) return { value: null, offset: line.offset };
        const items = [];
        let cursor = line.offset;
        for (let i = 0; i < count; i += 1) {
          const parsed = this._parseValue(cursor);
          if (!parsed) return null;
          items.push(parsed.value);
          cursor = parsed.offset;
        }
        return { value: items, offset: cursor };
      }
      case "%": {
        const count = Number.parseInt(text, 10);
        const object = {};
        let cursor = line.offset;
        for (let i = 0; i < count; i += 1) {
          const key = this._parseValue(cursor);
          if (!key) return null;
          const value = this._parseValue(key.offset);
          if (!value) return null;
          const name = Buffer.isBuffer(key.value) ? key.value.toString() : String(key.value);
          object[name] = value.value;
          cursor = value.offset;
        }
        return { value: object, offset: cursor };
      }
      case ">": {
        const count = Number.parseInt(text, 10);
        const items = [];
        let cursor = line.offset;
        for (let i = 0; i < count; i += 1) {
          const parsed = this._parseValue(cursor);
          if (!parsed) return null;
          items.push(parsed.value);
          cursor = parsed.offset;
        }
        return { value: items, offset: cursor };
      }
      default:
        throw new CrowkisError(`unexpected RESP frame: ${line.line.toString()}`);
    }
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.min(Math.max(Number(ms) || 0, 0), 2000)));
}

// The Python client's rule: a BUSY reply is retried after its retry-after-ms
// hint (50 ms without one), kept within 1 ms .. 2 s. Anything else: null.
function busyRetryMs(error) {
  if (!(error instanceof CrowkisError) || !/^BUSY/i.test(error.message)) return null;
  const marker = "retry-after-ms";
  const at = error.message.indexOf(marker);
  const digits = at < 0 ? null : /^[ =]*(\d+)/.exec(error.message.slice(at + marker.length));
  if (!digits) return 50;
  return Math.min(Math.max(Number(digits[1]), 1), 2000);
}

const NO_SERVER_TOKEN = /called without any password configured/i;

module.exports = { CrowkisError, toBuffer, encode, RespReader, sleep, busyRetryMs, NO_SERVER_TOKEN };
