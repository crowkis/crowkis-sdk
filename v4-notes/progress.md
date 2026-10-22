# v4 refactor: progress

Plan: `../sdk-docs/v4-refactor-plan.md` (unchanged). Work happens only in this clone, on `feat/v4`, branched
from `feat/env-config` at `835c533`. Nothing is pushed; pushes from this clone are blocked.

| Phase | Plan estimate | Status | Commits | Time spent |
|---|---|---|---|---|
| P0 safety net | 1 window | done (2026-10-22) | `1b4c4cc`, `e5c44aa`, `b8f592a`, `79ea0e6` | ~1 h 15 min |
| P1 rule chains in voice | 2-3 windows | done (2026-10-22) | `da6e0c2`, `2182580`, `b276d2b`, `6016501` | ~1 h 10 min |
| P2 runtime components, TurnCore | 1-2 windows | next | | |
| P3 Chat on the same core | 1-2 windows | | | |
| P4 pluggable understanding | 1-2 windows | | | |
| P5 v4 behaviour (opt-in) | 2 windows | needs the owner's OK (changes golden decisions) | | |

## P0 (done)

- `TurnDecision.rule` (question/hit rule) and `save_rule` / `saveRule` (save rule) on every voice decision,
  named as in the plan's section 4. Added fields only. `fixtures/decision-rules.json`, checked by
  `python/tests/test_decision_rules.py` and `node/test-decision-rules.js` (failed first, then passed).
- Golden files `fixtures/golden/<pipeline>/<suite>.json`: voice (`VoiceSession`) and Chat (`CallSession`) over
  the 277 rule phrases, the v1 and v2 stress calls and the conformance scenarios. Inputs frozen in
  `fixtures/golden/inputs.json` (`python/tests/golden/build_inputs.py`); Python writes the files
  (`python/tests/golden/replay.py`), `test_golden.py` and `test-golden.js` check them. Node reproduces
  Python's decisions exactly.
- Chat's understanding frames are stand-ins (fixed word checks), because the stress runs did not keep the
  LLM's frames. They pin Chat's rules on a fixed input; they are not a measure of Chat's quality.
- Golden suites: `phrases`, `stress-v1`, `stress-v2`, `conformance` (a store per scenario, with tool results
  and barge-ins), `hit-guards` (hand-written: every hit rule, answer shapes, declared values). Each call also
  pins `stats()` (voice) / `counts` (Chat).
- LiveKit (both languages) records through the core directly; its decisions now name their save rule too.
- Suites: Python 668 passed / 77 skipped, Node 39/39 files, each run twice. Real frameworks: Pipecat 1.13
  (26 passed), LiveKit Python 1.8.8 (23 passed), LiveKit JS (41 passed). Real server (`crowkis-demo`,
  tenant `voice`): conformance passes in both languages; container stopped.
- Reviews: privacy review, no blockers (real-looking contact details in the inputs swapped for fakes).
  Independent code review, no blockers; its five should-fix items are done in `79ea0e6`.

## P1 (done)

- Word detectors moved unchanged to `understanding/word_rules.py` / `src/understanding/wordRules.js`; every
  old name still imports from `crowkis.voice` / `voice.js`.
- 24 rule classes in `rules/question`, `rules/hit`, `rules/save` (both languages), run by `RuleChain`
  (first objection wins) from `RuleSet.voice()` (today's rules, today's order). Floor rules (`OwnRecords`,
  `PromptCallerDetails`, `PersonalTemplate`) cannot be turned off without `unsafe`; `PersonalTemplate` never.
  Unknown names and a single string are refused.
- Rules read value objects (`turns/`: `VoiceTurn`, `CachedAnswer`, `ModelAnswer`, `Verdict`) and the call
  through `VoiceCall` (`SessionCall` adapts the session). `WordRuleClassifier` + `NoRewrite` fill the
  understanding slots.
- `stats()` gains `rules` (per-rule counts). Golden decisions identical; the golden files changed only by
  that added key (checked field by field with `python/tests/golden/compare.py`).
- Per-rule fixtures `fixtures/rules/<stage>/<Rule>.json` test each rule alone in both languages. Node tests
  for new code live in `node/test/` (run by `run-tests.js`).
- Review: one Node blocker found and fixed (an `await` per rule let a `decide()` slip into `record()`); the
  chain now stays synchronous unless a rule must ask the server. Privacy review: no blockers.
- Suites: Python 684 passed / 77 skipped, Node 43/43 files, twice. Pipecat 26, LiveKit Python 23,
  LiveKit JS 41 passed.
- Real server: conformance fails one scenario ("a reworded question hits": the second caller's rewording
  reaches the LLM) in both languages, and fails the same way on the pre-P1 commit `0594148`, so it is not
  from P1. It passed at the end of P0 this morning; likely the shared `voice` tenant's state or the server's
  matching. Needs a look by the owner (not flushed).

## Notes and follow-ups

- For P4: `_model_messages`, `ModelAnswer.is_personal` and `PrivateChain`'s chain still call the word rules
  directly, not the turn's classifier reading. Before a classifier slot is public, route them through the
  reading (or treat a turn as personal if either says so), so a plugged-in classifier cannot make the
  question side and the save side disagree.
- Nits left: rules import `_`-prefixed names from `word_rules`; Node `src/rules/chain.js` requires
  `index.js` for `CrowkisError` (safe because `index.js` loads `voice.js` lazily); patching
  `crowkis.voice._sets_context` no longer reaches the rules (no test relies on it).

- Parity nit (existing): the commitment reason reads `commitments='exact'` in Python and `commitments="exact"`
  in Node. Mapped by name in `node/golden.js`; not changed (reason text is public behaviour).
- Rule names are coarse today: `_is_personal` covers urgent, unreadable and identifying turns, so they report
  `OwnRecords`; stale and talked-over turns both report `Interrupted`. P1 splits these into the plan's rules
  (`UrgentTurn`, `UnreadableText`, `IdentifyingDetails`, `StaleTurn`), which changes only the golden `rule` /
  `save_rule` names, never a decision. P1 checks that every other golden field is identical.
- Chat's golden hits come from its own saved answers only (the hit-guard seeds have no Chat segment).
- Rule names are string literals until P1 turns each rule into a class that owns its name.
- Framework environments for this work: `lk-venv`, `pc-venv` in this session's scratchpad; LiveKit JS in
  the older scratchpad `9b31f435-.../livekit-js`.

- `graphify` is not installed on this machine (`python -m graphify` missing either); code is found with grep.
- `npm run typecheck` needs `npm install` in `node/` (not run yet); `test-packaging.js` passes.
- `fixtures/voice-rule-phrases.json` (existing, not from v4) has the phrase "My email is rahul@gmail.com.";
  an `@example.com` address would be cleaner. Not changed here.
