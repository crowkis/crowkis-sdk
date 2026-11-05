# F8 golden changes

## Step 1: one pool per tenant (owner-approved 2026-11-05)

The voice segment is `kb=<knowledge_version>` for every session, with or without an understander
(before: none without an understander, `kb=<v>;channel=<name>` with one).

- `fixtures/golden/voice/*.json`: 430 writes now carry segment `kb=1` instead of `""`. No decision, rule,
  reason or counter changed. (The golden harness seeds the voice store under `kb=1`; the chat
  golden files are untouched.)
- Cold cache, once: answers saved by an older SDK (no segment, or `kb=..;channel=..`) are not found
  by 0.6.0. The pool refills on use. Put this in the 0.6.0 release notes.
