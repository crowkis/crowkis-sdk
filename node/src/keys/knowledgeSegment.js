"use strict";

// CRC-32 (the zlib polynomial), the same hash as Python's zlib.crc32, so both SDKs key a
// tailored answer the same way. Written out because zlib.crc32 needs Node 20.15 or 22.2.
const CRC32_POLYNOMIAL = 0xedb88320;
const CRC32_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let bit = 0; bit < 8; bit++) c = c & 1 ? CRC32_POLYNOMIAL ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC32_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

const { FUNCTION, TOLD_TYPES, stem, toks } = require("../understanding/frameWords.js");

// A value can never add or change a field of the segment.
const FIELD_BREAKERS = /[;=\s]+/g;

/** The question alone: it is what is embedded and matched, so nothing else may be in its text. */
function key(question) {
  return question.split(/\s+/).filter(Boolean).join(" ");
}

/** A voice turn's key: its words as said, or the earlier turns it leans on joined to it. */
function followUpKey(said, chain = null) {
  return chain && chain.length ? [...chain, said].join(" || ") : said;
}

/** `name=value;...`: a value can never add or change a field, and whitespace is collapsed. */
function segment(fields) {
  return fields
    .map(([name, value]) => `${name}=${String(value).replace(/[;=]/g, "_")}`.split(/\s+/).filter(Boolean).join(" "))
    .join(";");
}

function keyAttributes(frame, state, question) {
  const attrs = {};
  for (const name of ["segment", "region"]) {
    const attr = frame.attributes[name];
    if (attr && attr.changesAnswer) attrs[name] = attr.normalised;
  }
  // Location rule: a question about a named local place, or a search, carries the call's location.
  if ((frame.questionType === "place_fact" || frame.questionType === "search") && !attrs.region) {
    const region = frame.attributes.region || state.attributes.region;
    if (region) attrs.region = region.normalised;
  }
  // What the question already says keeps it apart by itself ("the capital of France" is not "the
  // capital of Spain"); in the segment too it would only split equal questions.
  const qwords = new Set(toks(question));
  for (const [name, value] of Object.entries(attrs)) {
    // The place itself, all of it, word for word: "goa" of "goa, india"; "new york" is not "new".
    const words = toks(value.split(",")[0]).filter((w) => !FUNCTION.has(w));
    if (words.length && words.every((w) => qwords.has(w))) delete attrs[name];
  }
  return attrs;
}

// What the question carries from what the caller told (their facts, the details of this turn):
// a short hash of those words, or null for a question anyone could ask. Two callers with a
// peanut allergy share answers; peanut and shellfish never do.
function told(frame, state, question) {
  const heard = [...state.stated,
    ...state.facts.filter((f) => TOLD_TYPES.has(f.split(":")[0])).map((f) => f.split(":").slice(1).join(":")),
    // In the question itself only a condition tailors it ("for someone with a peanut allergy"); a
    // place, time or amount there is part of what anyone could ask.
    ...frame.entities.filter((e) => e.type === "condition" && !e.identifying).map((e) => e.text)];
  const toldStems = new Set(heard.flatMap((t) => toks(t)).filter((w) => !FUNCTION.has(w)).map(stem));
  const carried = [...new Set(toks(question).filter((w) => !FUNCTION.has(w)).map(stem))].filter((w) => toldStems.has(w)).sort();
  return carried.length ? crc32(Buffer.from(carried.join(" "))).toString(16).padStart(8, "0") : null;
}

/**
 * `kb=<version>;channel=<name>`: answers made with one understanding (its prompt, its model) and
 * knowledge version only ever meet each other, so switching understanders, or the knowledge behind the
 * answers, is a deliberate new version, never a silent mix. Chat builds the same fields in its own,
 * longer segment (RuleChecker.buildSegment).
 */
class KnowledgeSegment {
  constructor(version, channel) {
    this.version = String(version).trim().replace(FIELD_BREAKERS, "_") || "1";
    this.channel = channel;
  }

  get segment() {
    return segment([["kb", this.version], ["channel", this.channel.name]]);
  }
}

module.exports = { KnowledgeSegment, followUpKey, key, keyAttributes, segment, told };
