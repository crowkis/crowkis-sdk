"use strict";

// A value can never add or change a field of the segment.
const FIELD_BREAKERS = /[;=\s]+/g;

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

/**
 * `kb=<version>`: one pool per tenant. Answers made with one knowledge version only ever meet each
 * other, so changing the knowledge behind the answers is a deliberate new version, never a silent
 * mix. Voice and chat, with or without an understander, share it.
 */
class KnowledgeSegment {
  constructor(version) {
    this.version = String(version).trim().replace(FIELD_BREAKERS, "_") || "1";
  }

  get segment() {
    return segment([["kb", this.version]]);
  }
}

module.exports = { KnowledgeSegment, followUpKey, segment };
