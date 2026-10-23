# v4 refactor: progress

Plan: `../sdk-docs/v4-refactor-plan.md` (unchanged). Work happens only in this clone, on `feat/v4`, branched
from `feat/env-config` at `835c533`. Nothing is pushed; pushes from this clone are blocked.

| Phase | Plan estimate | Status | Commits | Time spent |
|---|---|---|---|---|
| P0 safety net | 1 window | done (2026-10-22) | `1b4c4cc`, `e5c44aa`, `b8f592a`, `79ea0e6` | ~1 h 15 min |
| P1 rule chains in voice | 2-3 windows | done (2026-10-22) | `da6e0c2`, `2182580`, `b276d2b`, `6016501`, `d54dbfd`, `6a9fc92` | ~1 h 35 min |
| P2 runtime components, TurnCore | 1-2 windows | done (2026-10-22) | `91529cc`, `b261b6d`, `c12d137`, `c561c3e`, `6d7073c` | ~1 h 25 min |
| P3 Chat on the same core | 1-2 windows | done (2026-10-22) | `817f642`, `3a9c2d3`, `2fc5d7d`, `712d0ef`, `ac43e2c`, `6c90229`, `cfda1ad` | ~2 h 30 min |
| P4 pluggable understanding | 1-2 windows | in progress (owner: start 2026-10-22; stop lines 97% 5-hour and weekly) | | |
| P5 v4 behaviour (opt-in) | 2 windows | needs the owner's OK (changes golden decisions) | | |
| P5.5 clean code (owner, 2026-10-22) | after P5 | not started (in the plan file, owned by the orchestrating session) | | |
| P5.5 clean-code pass (owner, 2026-10-22) | 1-2 windows | after P5: re-check every file, refactor the ones not clean; see plan P5.5 and `v4-notes/review-later.md` | | |
| P5.6 remove the old paths (owner, 2026-10-23) | | after P5.5: owner exception to the change wall (pre-launch, 0.5.2 unpublished); delete the re-export modules once every user (integrations, tests, docs, six outside scripts) imports the new paths; see plan P5.6. Nothing in P4 changes. | | |

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

## P4 (in progress; owner started it 2026-10-22 ~19:15 IST)

**Stopped 2026-10-22 (owner: stop for the day; no timer).** Steps 1-3 are committed, both suites green
(Python 711 passed, Node 50/50, each run twice), golden files untouched. Restart after the weekly reset
(2026-10-23 13:00 UTC) with step 4. Usage at the stop: 5-hour about 90%, weekly 91%.

Stop lines: 97% on the 5-hour limit (then a background timer to its reset, 17:20 UTC, and continue while the
weekly allows) and 97% weekly (then stop, no timer; the owner restarts after 2026-10-23 13:00 UTC). Check
usage before every step; small commits; golden identical; both suites green at every commit.

Steps (each its own commit, both languages):
1. [done] Typed `Hit` (deferred from P2): `turns/hit.py` / `src/turns/hit.js` value object built once from the agent's
   hit dict in the lookup; hit rules read its fields instead of `hit.get(...)`. No behaviour change.
2. [done] `Classifier` / `Rewriter` slots wired through: `VoiceSession(..., classifier=None, rewriter=None)` and
   `voice_session(...)` / `async_voice_session(...)` / Node `voiceSession(...)` pass them through (defaults:
   `WordRuleClassifier`, `NoRewrite`, so nothing changes). Adapters need no edits (options pass through).
3. [done] The reading everywhere (privacy review finding): `_model_messages`, `ModelAnswer.is_personal` and
   `PrivateChain` read the turn's reading, or treat a turn as personal if either the reading or the word rules
   say so (never less private). Golden identical with the default classifier.
   Built as `understanding/call_readings.py` / `src/understanding/callReadings.js` (`CallReadings`:
   `note`, `is_personal`, `chain_is_private`), one per session, injected into `TurnCore` (`call_readings=`),
   offered to rules as `VoiceCall.is_personal(text)`. `TurnCore`'s constructor gained a required
   `call_readings` argument; `tests/turns/test_turn_core.py` / `turnCore.test.js` pass it (setup only).
   Not yet reviewed: the code + privacy review of steps 2-3 belongs to step 6.
4. [next] `LLMClassifier` / `LLMRewriter` split from `LLMUnderstander` (any provider via one `complete`), plus
   `ReplayRewriter` (exact repeats) and `BudgetedUnderstanding` (Decorator: the channel budget; late or failed
   means the word rules decide, never "share anyway"; counts `understand_timeouts` / `understand_errors`).
   `LLMUnderstander` keeps working as both slots for Chat.
5. `channel=` profiles in the factories; v4 conformance scenarios with an understander in
   `fixtures/adapter-conformance.json` (Pipecat, LiveKit Python, LiveKit JS).
6. Reviews (code + privacy), real-server check, mark P4 done.

## P3 done (2026-10-22); work stopped (owner: no P4 today)

- Final review (code + privacy) of `3bae579..cfda1ad`: no blockers. Logged nits, not fixed: unused imports and
  stray blank lines in `session.py` / `session.js` (and Node's unused `LOOKUP_COUNTS`), a JSDoc comment above
  `handle()` that belongs to `recordAnswer`, `CacheLookup`'s late-path `.catch` on a non-standard thenable, and
  the lookup-deadline reason saying "voice budget" on Chat's lookups (left: reason text is public behaviour).
- Suites: Python 704 passed / 77 skipped, Node 49/49 files, twice; golden identical. Real server: only the
  pre-existing "a reworded question hits" fails.
- Next when the owner restarts: P4 (pluggable understanding), after the weekly reset.

## Where the work stopped, and how to continue (2026-10-22, ~19:00 IST)

- **Clean point:** everything committed (last code commit `5382d42`), Python 702 passed / 77 skipped, Node
  48/48 files, golden decisions identical. Paused for the weekly limit (85%); the owner restarts the work
  after the weekly reset (2026-10-23 13:00 UTC). No timer is set for it.
- **Current step: P3's last piece.** `CallSession` and `Chat` on the shared turn core with a `ChatChannel`
  profile (value object: budget ~1000 ms, no audio, not spoken, saves answers), and Chat's lookup through
  `runtime/CacheLookup` (adapt its counters: Chat counts `lookup_timeouts` / `lookup_errors` in `counts`).
  Golden Chat decisions must stay identical; Chat's tests unchanged.
- **Resumed 2026-10-22 (owner: finish P3 today, weekly line 98% for P3 only, then stop; no P4).** Steps:
  (1) channel profiles `turns/channel` (`VOICE`, `CHAT`, `REALTIME` per plan §3.3); (2) Chat's lookup through
  `CacheLookup` with `refuse_late_hits=False` (Chat never refused a late hit; voice does); (3) Chat's turn flow
  into `ChatCore` (Template Method beside the voice `TurnCore`, typed parts, a `ChatHost` interface the session
  implements), `CallSession` delegating. One core class for both channels needs Chat's steps generalised and is
  left to P5 (noted for the owner).
  **Status:** steps (1) and (2) done in `ac43e2c` (golden identical, Python 704, Node 49/49). Next: step (3)
  `ChatCore`: move `CallSession.handle` / `_record` (and `_understand`, `_lookup`) into
  `turns/chat_core.py` / `src/turns/chatCore.js`, with a `ChatHost` Protocol (state, counts, fillers, mode,
  hooks, emit, open/cancelled turns) the session implements through an adapter, like `SessionHost`. Then P3
  reviews (code + privacy), real-server conformance, and mark P3 done.
  **Step (3) Node done** in `cfda1ad` (`src/turns/chatCore.js`, `turnResult.js`, `understanding/chatDetails.js`).
  Suites: Python 704 passed, Node 49/49, golden identical. Real server: only "a reworded question hits" fails,
  as on `0594148`. Remaining: the final P3 review's findings, then mark P3 done (owner: then stop, no P4).
  **Step (3) Python done** (commit after `2268883`): `turns/chat_core.py` (`ChatCore`, owns its lookup, rule
  chains and turns), `turns/chat_host.py` (`ChatHost` Protocol; `CallSession` implements it: `fillers`,
  `emit`, `prompt_key` added as public members), `turns/turn_result.py`, `FILLER` in `turns/routes`, the
  helpers in `understanding/chat_details.py`; everything re-exported from `session.py`; `CallSession._lookup`
  kept as a delegate (two tests call it). **Next: the same in Node** (`node/session.js` -> `src/turns/chatCore.js`,
  `chatHost` typedef, `turnResult.js`, `understanding/chatDetails.js`), then reviews, real server, P3 done.
- **Owner decision (2026-10-22): option (b).** Chat keeps waiting for its writes, and only the lookup deadline
  moves to `CacheLookup`, so Chat's outcomes do not change. Chat's `BoundedWrite` (with the new `slow_write`
  outcome) is **deferred to P5 item 3**, as an opt-in behaviour change with failing-first tests.
- **Open review findings:** none blocking. Deferred to P4: rules read the classifier's reading instead of
  private `word_rules` functions (and `_model_messages`, `ModelAnswer.is_personal`, `PrivateChain`'s chain
  too), a typed `Hit` instead of the raw hit dict. Pre-existing, logged only: the "refused" warning logs
  `str(error)`; `TurnPairing.start()` / `record_private_turn` flags outside the lock; the real-server
  conformance scenario "a reworded question hits" fails since this morning (also on `0594148`).
- **After P3:** reviews (code + privacy, subagents), real-server conformance (`docker start crowkis-demo`,
  tenant `voice`, never flush, stop afterwards), progress note, then P4.
- **Usage rules (owner):** check `mcp__ccd_session_mgmt__get_usage` before every step. 5-hour limit: stop at a
  clean point before a step that would pass 97%, then wait for its reset with a background timer and
  continue. Weekly limit: never start a step that could take it past 95%; stop at a clean point, note it
  here, and do not set a timer (the owner restarts).
- **Environments:** framework venvs in this session's scratchpad (`lk-venv` LiveKit 1.8.8, `pc-venv` Pipecat
  1.13); LiveKit JS under the older scratchpad `9b31f435-.../livekit-js/node_modules` (`NODE_PATH`). Commits:
  no co-author trailer; push nothing (pushes from this clone are blocked).

## P2 follow-ups (owner request, 2026-10-22, done before resuming P3)

- `Stats` (`runtime/stats.py`, `src/runtime/stats.js`): the session's counters and per-rule counts, injected
  into `TurnCore` and the writer; counter names are an enum (`Counter`) / constants (`COUNTER`) carried by
  rules. The public counters (`session.filled`, ...) read and write it (a descriptor in Python, prototype
  accessors in Node), so their names, values and `stats()` are unchanged.
- `TurnCore` reaches nothing private: it uses `TurnHost` (transcript, agent, settings, audio, writes), which
  `SessionHost` adapts, and `Stats` for counters. Its constructor takes typed collaborators (`RuleSet`,
  `VoiceCall`, `TurnPairing`, `CacheLookup`, `Classifier` / `Rewriter` from `understanding/slots`, `Stats`).
- Registered fillers are the `RegisteredFiller` rule (stage 1, operational) in `RuleSet.filler`.
- Commit `c709e34`; golden identical; slow-server and barge-in tests unchanged; frameworks pass.
- Review of the cleanup: no blockers; nits fixed in `5382d42`. Visible for anyone who dumps a session: the
  counters are no longer the session's own attributes (`vars(session)`, `Object.keys`, `JSON.stringify` no
  longer list them; reading and writing them works as before). `RegisteredFiller` can now be named in
  `RuleSet.without` (it was not a rule before).
- Left for P4 as planned: rules reading the classifier's reading instead of private `word_rules` functions,
  and a typed `Hit` instead of the raw hit dict.

## P3 (in progress)

- Done: every Chat check is a rule class, one per file, in `rules/question` and `rules/save` (both languages):
  V1-V10 (`UrgentTurn`, `TaskStep`, `UncertainFrame`, `NotGeneral`, `AboutSomeone`, `NoQuestion`,
  `IdentifyingDetails`, `Ungrounded`, `UnresolvedReference`, `LostDetail`, `StatedFacts`), the session's
  checks once a question would be shared (`QuestionNamesCaller`, `ToldDetailDropped`, `UntaggedName`,
  `UrgentWords`) and `save_check` (`ChatEmptyAnswer`, `ChatNonAnswer`, `IdentifyingAnswer`, `ActionClaim`,
  `AttributeNotInKey`, `PrivateWord`, `ChatPromptDetails`), run by `ChatRuleSet`. `RuleChain` gained
  `all_objections` (Chat reports every objection) and nesting (V7 is "lost detail, else dropped fact").
  Golden Chat decisions identical; per-rule fixtures for all 46 rules.
- "Chat..." names mark rules whose voice twin has different code today; P5's merged save check joins them.
- P3 reviews (code, privacy): no blockers. To fix before P3 ends: a nested group named in `without()` must not
  drop a floor rule inside it; `NotGeneral` becomes a floor rule; Node `allObjections` fails loudly on a
  promise; nits (dead `escapeRe`, unused imports in `verify.js`, an 8+-word V6 case, a multi-reason
  `RuleChecker.check` case, a fake-looking phone number in a fixture).
- Left: `CallSession` / `Chat` on the shared turn core with a `ChatChannel` profile, and Chat's writes through
  `BoundedWriter` and lookups through `CacheLookup`, without changing its outcomes.

## P2 (done)

- Done: `runtime/` in both languages: `WriteWorkers` + `BoundedWriter` (bounded writes; old module names
  `_PENDING_WRITES`, `_submit_write`, `_wait_for_writes`, `_WRITES_MAX`, Node `_setWritesMax` still work),
  `CacheLookup` (the one place a lookup fails open; the budget is read per lookup), Node `deadline.js`
  (`within`, `LATE`), `TurnPairing` (turn numbers, barge-in, the per-turn shareable flag; Python keeps
  `session._turn_lock` as its lock). Unit tests for each; golden decisions identical; frameworks pass.
- `TurnCore` (Template Method; `turns/turn_core.py`, `src/turns/turnCore.js`) owns decide and record, with
  the rules, classifier, rewriter, turn pairing and lookup injected; `VoiceSession` keeps the transcript,
  fillers, audio, counters and the public API and delegates (`AsyncVoiceSession` already wraps it).
  `TurnDecision` / `_Outcome` live in `turns/decision` (re-exported). `voice.py` ~3,100 -> ~1,430 lines,
  `voice.js` -> ~1,240.
- Suites: Python 694 passed, Node 46/46 files, twice; Pipecat 26, LiveKit Python 23, LiveKit JS 41.
  Real server: as after P1, only "a reworded question hits" fails (it fails on `0594148` too).
- Reviews: code review and privacy review, no blockers. Fixed: Node `_lookup` no longer adds await steps;
  the core's host contract is written down (`TurnHost`); the pending-write and lock nits.
- Owner change 2026-10-22: the 5-hour stop line is 97% (stop at a clean point, wait for the reset with a
  background timer, then continue).

## Owner changes to the plan

- 2026-10-22, plan §3.5: **one rule per file** inside its stage folder, the file named after the class
  (`rules/question/cut_off.py` -> `CutOff`; Node `src/rules/question/cutOff.js`), replacing the theme files
  (`guards.py`, `answer.py`, `floor.py`, ...). Each stage's `__init__.py` / `index.js` exports its rules for
  `RuleSet`. Per-rule fixtures stay `fixtures/rules/<stage>/<Rule>.json`; one fixture-driven test per
  language runs every rule file (`tests/rules/test_stage_rules.py`, `node/test/rules/stageRules.test.js`).
  Applied in a follow-up commit, since the grouped files had already been committed.
- 2026-10-22, owner request (CLAUDE.md §4, no helpers module): `understanding/word_rules.py` is split by
  theme into the package `understanding/word_rules/` (Node `src/understanding/wordRules/`): `text`
  (shared primitives), `phrases` (word tables more than one theme reads), `urgent`, `personal`,
  `identifiers`, `follow_up`, `call_context`, `answers`, `prompt_details`. **Chosen: option 1 (split by
  theme)**, because it moves every statement verbatim (checked by AST in Python, line by line in Node) with
  no change in logic, so it is safe inside a no-behaviour-change phase; imports point one way
  (`text` <- `phrases` <- the themes). Option 2 (detectors behind `WordRuleClassifier` with a typed result)
  changes how every rule reads a turn and belongs with P4, where the classifier slot becomes pluggable.
  The package `__init__` / `index.js` re-exports every name, so `crowkis.voice._x` and
  `crowkis.understanding.word_rules._x` keep working; word lists stay named constants.

## Notes and follow-ups

- Pre-existing (privacy review, P2): the "refused" warning logs `str(error)`, the server's error text,
  which could echo a key; logging only the error type would be safer. Not changed (log text is behaviour).
- Pre-existing: `TurnPairing.start()` and the `open` / `cancelled` flags set by `record_private_turn` run
  outside the lock, as the old fields did.

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
