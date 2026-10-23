"use strict";

// A value can never add or change a field of the segment.
const FIELD_BREAKERS = /[;=\s]+/g;

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
    return `kb=${this.version};channel=${this.channel.name}`;
  }
}

module.exports = { KnowledgeSegment };
