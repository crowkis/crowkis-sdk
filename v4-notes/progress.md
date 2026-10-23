# v4 refactor: progress

Plan: `../sdk-docs/v4-refactor-plan.md` (unchanged). Work happens only in this clone, on `feat/v4`, branched
from `feat/env-config` at `835c533`. Nothing is pushed; pushes from this clone are blocked.

| Phase | Plan estimate | Status | Commits | Time spent |
|---|---|---|---|---|
| P0 safety net | 1 window | done (2026-10-22) | `1b4c4cc`, `e5c44aa`, `b8f592a`, `79ea0e6` | ~1 h 15 min |
| P1 rule chains in voice | 2-3 windows | done (2026-10-22) | `da6e0c2`, `2182580`, `b276d2b`, `6016501`, `d54dbfd`, `6a9fc92` | ~1 h 35 min |
| P2 runtime components, TurnCore | 1-2 windows | done (2026-10-22) | `91529cc`, `b261b6d`, `c12d137`, `c561c3e`, `6d7073c` | ~1 h 25 min |
| P3 Chat on the same core | 1-2 windows | done (2026-10-22) | `817f642`, `3a9c2d3`, `2fc5d7d`, `712d0ef`, `ac43e2c`, `6c90229`, `cfda1ad` | ~2 h 30 min |
| P4 pluggable understanding | 1-2 windows | done (2026-10-23) | `dba85e0`, `241e1ab`, `df50e41`, `4b7c60e`, `821c0f2`, `94f249b`, `d6b2d3d`, `255ff9b`, `b907566`, `dd1f5f5`, `2caeaf7`, `b293b55`, `af4375f`, `91ab247`, `0f5aae3` | ~2 h 15 min |
| P5 v4 behaviour (opt-in) | 2 windows | in progress: items 1-5 committed; reviews, frameworks and real server next | `d295214` ... `45c1fa1` | |
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

## P5 (in progress; owner approved 2026-10-23: items 1-5, only on the understander path)

Usage rules: 5-hour stop before 97% at a clean point, then a background timer to the reset (18:40 UTC) and continue;
weekly stop before 95%, no timer. After P5: stop and report (P5.5 not approved yet).

Items, each failing-first in both languages with must-still-work controls (all committed, both suites green):
1. [done] `d295214` / `06e720a`: StatedFacts with relevance. `TurnFrame.fact_relevance` (+ prompt). `FactRelevanceCheck`:
   a stated fact may be left out only when the model is sure and tags it irrelevant; allergy, medication, pregnancy,
   age always count (`word_rules/high_risk.py`, the floor). Chat V7 uses it. Voice with a classifier runs
   `RuleSet.understood()`: `VoiceStatedFacts` replaces `CallContextTaint` (keeps just the stating turn and each turn a
   fact may change private; `mark_private`); the classifier reads the call's de-identified facts (frames' memorable
   entities), never its turns. Unsure / late / failed / no model: strict as before. `RuleChain.replacing()`.
2. [done] `b324cb5` / `ec1e5e3`: hit guards on every channel. `QuestionRecords` (runtime; voice delegates unchanged).
   Chat's lookup runs PiiPlaceholder, DifferentQuestion, CommitmentRewording (exact only, V2) via `ChatCachedAnswer`;
   a refused hit is counted by its rule name; Chat keeps question records when it saves.
3. [done] `d307c95` / `d8fbff0`: merged save check. Voice (understood) gains `VoicePrivateWord`, `VoiceActionClaim`.
   Chat gains `ChatToolResult` (`record_answer(private=True)`), `ChatCallerIdentifier` (hashed `identifiers` in the
   chat state; note: today `PrivateWord` refuses these first, since an ID turn is never shared, so this is defence in
   depth) and the bounded write (2x budget, then `slow_write`).
   Fix `8f273c9` / `10ba7e6`: the told-facts / private-word collection ran on the default path (+0.2 s on a 22,500-word
   turn, `test_review_11` flaky); now only with an understander.
4. [done] `d82adde` / `b8c81e9`: the 2026-10-22 misfires (cases in `v4-notes/p5-misfires.md`): common acronyms are no
   names (B05), a generic payment method is not identifying (B04), a stem starting another of 5+ letters is grounded
   (B03), a clock time while a task runs is a task step (C01); V7 on unrelated facts is item 1.
5. [done] `3143540` / `45c1fa1`: `kb=<version>;channel=<name>` (`keys/KnowledgeSegment`) on every voice lookup and save
   with an understander (`knowledge_version=`, default "1"); Chat already had kb= in its segment.

**Golden:** voice identical. Chat: 38 turns changed, all in item 4 (the acronym list, plus one knock-on); every one is
listed by rule in `v4-notes/p5-golden-changes.md` for the owner.

**Done since:** conformance with the P5 code passes on Pipecat 1.13 (45 runs), LiveKit Python 1.8.8 and LiveKit JS (49/49).

**Stopped 2026-10-23 ~15:40 UTC at 97% of the 5-hour limit (clean: `5c9dd46`, both suites green). A background timer
restarts at the reset (18:40 UTC).** The code review was still running at the stop; read its report first.

**Privacy review findings, to fix next (both languages, failing-first):**
1. Medium: the classifier now sees the call's facts, so `LLMRewriter` can put a told fact into a shared key
   ("what foods should someone with liver cirrhosis avoid?"). Fix: `RewriteCheck` refuses a rewrite once the call has
   stated turns or facts (`call.stated()` / a new `call.facts()`).
2. High (the floor): `_high_risk` misses "my son is 3", "she is 80", number words ("three", "ninety"), "3yo", drug
   names (warfarin, metformin), chronic conditions (diabetic, kidney disease, epilepsy, asthma, stroke), "8 months
   along", Spanish / Hindi pregnancy and age words. Fix: a digit or number word next to a relation word or pronoun is
   an age; add number words, "yo", condition and common-drug lists, es / hi words.
3. Medium: one irrelevant fact excuses a whole stated turn ("heart condition and going to Goa" + "trip: Goa"
   irrelevant). Fix: split the stated turn into clauses; every clause needs its own irrelevant fact.
4. Medium: `changes_answer` "unsure" / "" / "maybe" read as irrelevant. Fix: only false / "false" / "no" / 0 are.
5. Medium: `identifiers` are unsalted 16-hex digests of low-entropy IDs in `export()`. Fix: leave them out of the
   export (in-memory only).
6. Low-Medium: the acronym list matches case-insensitively, so "Ram" / "Sim" pass `UntaggedName`. Fix: exempt
   all-caps tokens only.
7. Low (note): golden A09 "Do I need an ID proof for that?" now shared under its own words (stand-in frame).

**Code review findings (arrived after the stop), to fix with the above:**
- BLOCKER: on the understander path, a heard turn (`_heard`: `record_private_turn`, Pipecat / LiveKit history) only
  sets `_tainted`; `VoiceStatedFacts` never reads it, so a later turn can be *served* (saving is still blocked by
  TaintedCall). Fix: `VoiceStatedFacts` keeps a turn private when `call.tainted`, or `_heard` adds stated turns via
  `CallReadings` (guarded by `remembers_told`); fixture case; both languages. Repro: scratchpad `rev/test_heard2.py`.
- HIGH: same as privacy 3 (one irrelevant entry clears a two-fact turn). Repro: `rev/test_unit_rel.py`.
- MEDIUM: Python calls `classify(text, facts)`; a P4-style `classify(self, text)` classifier raises TypeError and
  silently falls back on every turn (Node ignores the extra argument). Fix: pass facts only when the classifier's
  signature takes them (checked once), in TurnCore and BudgetedUnderstanding.
- MEDIUM: Python Chat question records run on Chat's lookup pool (`submit_write=_LOOKUPS.submit`). Fix:
  `_voice._submit_write`.
- LOW: `index.d.ts` lacks `classify(text, facts?)`, `Reading.frame`, `TurnFrame.factRelevance`, `CallState.identifiers`
  / `details`; `LLMClassifier` d.ts comment stale; `voice.py` imports `hashlib` / `json` unused; `_COMMON_ACRONYMS`
  sits between `_GENERIC_FACT`'s comment and its definition (both languages).
- Notes for the docs (no fix): a rewriter alone turns on `kb=` but not `RuleSet.understood()`; `warm_from_calls` saves
  without a segment (its answers are not found by an understander session); Chat now reads a question record on a hit,
  bounds saves at 2x budget (`slow_write`) and counts refused hits by rule name.

Then: real-server check, mark P5 done, stop and report (P5.5 not approved).

## P4 done (2026-10-23)

- **Done when, checked:** golden files untouched by every P4 commit (no understander: identical); conformance with the
  four v4 scenarios (an understander) passes on the custom loops, Pipecat 1.13, LiveKit Python 1.8.8 and LiveKit JS
  (`af4375f`, re-run after the review fixes); both suites green twice (Python 744 passed, Node 54/54 files).
- **What it added:** `classifier=` / `rewriter=` on `VoiceSession` and the factories; `CallReadings` (a turn is personal
  or a follow-up by its reading OR the word rules; each turn sets or clears its rewrite; the answer is saved under the
  key it was looked up with); `FrameReading`, `LLMClassifier`, `LLMRewriter`, `ReplayRewriter` (exported);
  `RewriteCheck` (a rewrite keys only a general, stand-alone turn and adds no number, capitalised name or declared
  value); `BudgetedUnderstanding` (every plugged-in model: error boundary, budget from the channel, word rules on a
  late or failed model, `understand_timeouts` / `understand_errors` in `stats()` only when a model is plugged in;
  Python bounds a session's late calls at 4 and cancels them); `channel=` profiles (`Channel.of`, exported).
- **Reviews:** code + privacy (two subagents). Fixed in `91ab247` / `0f5aae3`: stale rewrite used as the save key;
  a model could drop a word-rule follow-up (leaking a private chain's words into a lookup key); a rewrite used for a
  word-personal turn (template under a general key) and for a follow-up (answer built from the chain saved under a
  bare question); an unchecked rewrite carrying invented details; no error boundary without a budget; a hung model
  holding every shared worker (Python); blank rewrites; `Channel` not exported / typed as an interface. The privacy
  reviewer re-checked: all fixed.
- **Tests changed, not added:** `test_slots_wired` / `slotsWired.test.js` "the factory passes them through" now
  expects the slots inside `BudgetedUnderstanding`; `test_budgeted_understanding` / `budgetedUnderstanding.test.js`
  "no budget runs the model as it is" asserted the unguarded model (a bug) and now expects the guarded one;
  `test_turn_core` / `turnCore.test.js` pass the new `call_readings` argument (setup only).
- **Real server** (`crowkis-demo`, tenant `voice`, stopped after): every v4 scenario passes in both languages. Two
  failures, both also on the pre-v4 base `835c533` (checked today), so server-side: "a reworded question hits"
  (known) and, new today, "Unicode, Hinglish and numbers" (the Spanish turn's new answer is not findable by the
  next caller; earlier runs passed on an older stored copy). For the owner; not flushed.
- **Known limits, for the owner (not fixed):** `RewriteCheck` catches capitalised names only, so a lowercase name
  the model invents can key a turn (the model sees the turn alone, so it cannot carry this caller's other details;
  no worse than today's key, the caller's words). A wrong rewrite can store an answer under an unrelated question
  (cache poisoning by a bad model; P5 item 2's hit guards are the defence). `_chain()` walks back by the word rules
  only. Channel fields other than `spoken` and the budgets are informational until P5. Python's understanding pool is
  module-level like the lookup pool. Node logs through `console.warn`, like `BoundedWriter`. `CallReadings` sets grow
  with the call's distinct turns.
- **Logged nits:** Node validates the client before `Channel.of`, Python after (error order only).

## P4 steps (2026-10-22 to 2026-10-23)

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
4. [done] `LLMClassifier` / `LLMRewriter` split from `LLMUnderstander` (any provider via one `complete`), plus
   `ReplayRewriter` (exact repeats) and `BudgetedUnderstanding` (Decorator: the channel budget; late or failed
   means the word rules decide, never "share anyway"; counts `understand_timeouts` / `understand_errors`).
   `LLMUnderstander` keeps working as both slots for Chat.
5. [done] `channel=` profiles in the factories; v4 conformance scenarios with an understander in
   `fixtures/adapter-conformance.json` (Pipecat, LiveKit Python, LiveKit JS).
6. [done] Reviews (code + privacy), real-server check, mark P4 done.

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
