# U1: ponytail ultra pass over `understanding/` (2026-11-04)

Read-only, at `5403b05` (after T2). Scope: `python/crowkis/understanding/` (28 files with `word_rules/`) and
`node/src/understanding/` (25 files). Nothing in the code changed. Callers were counted with an AST pass over
`python/` (package, tests; `python/build/lib/` is a stale build copy and was left out), a `require` pass over
`node/` (src, tests, `index.js`, `index.mjs`, every `.d.ts`), `examples/` and the Bolna integration.

**Hard limits kept.** No proposal changes a decision (golden files would stay identical). Public names don't change:
`crowkis/__init__.py` (`TurnFrame`, `LLMUnderstander`, `ReplayUnderstander`, `WithFallback`, `LLMClassifier`,
`LLMRewriter`, `ReplayRewriter`), `crowkis.privacy` (it imports 7 word-rule names; its own exports stay), and Node
`index.js` / `index.mjs` / `index.d.ts`. Every error boundary (`BudgetedUnderstanding`, `WithFallback`) keeps its
handling. None of the names this report deletes or moves is public.

**Risk:** *none* = imports or types only; *low* = a class becomes a function with the same body, or code moves
between modules; *needs tests* = a signature changes that a test or a caller could pass.

---

## What the pass found

- **No dead code inside `understanding/`.** Every top-level name in all 28 Python files is read somewhere, and every
  relative import inside the package is used.
- **The bulk is re-exports.** `word_rules/__init__.py` re-exports 261 names (283 lines). Only **42** of them are
  imported through the package by anyone other than one facade. That facade, `channels/voice_session.py`, imports
  **258** of them and uses **4** (`_COMMITMENTS`, `_carries_call_context`, `_normalise`, `_sets_context`). The same
  holds for `channels/call_session.py` (17 understanding names, 0 used) and `rules/rule_checker.py` (18, 0 used).
  Node mirrors it: `voiceSession.js` destructures 269 names from `wordRules/index.js` and uses 25.
- **The four Protocols each have several implementations** (see "Keep"), so none of them goes.

## Files and lines

| | Files before → after | Lines before → after (approx.) |
|---|---|---|
| Python `understanding/` | 28 → 14 | 3,930 → ~3,630 (−300 in the folder) |
| Python outside it (facades, `rule_checker`) | | −290 |
| Node `understanding/` | 25 → 11 | 3,415 → ~3,380 (−35 in the folder) |
| Node outside it (facades, `ruleChecker`) | | −265 |

The file count falls through the regrouping in `understanding-layout-plan.md`. The lines fall mostly outside the
folder, because that is where the unused re-exports live.

---

## Ranked findings

Callers are listed as `py:` / `node:` paths relative to `python/` and `node/`.

| # | Finding | Files (Python / Node) | Action | Lines saved (py / node) | Risk | Callers to repoint |
|---|---|---|---|---|---|---|
| 1 | **`word_rules/__init__.py` is 283 lines of re-exports.** 42 names are imported through it (by 36 files besides `voice_session.py`): text 7, personal 7, answers 6, phrases 5, identifiers 4, follow_up 4, call_context 3, prompt_details 3, high_risk 2, urgent 1. Node's `wordRules/index.js` spreads every module. | `word_rules/__init__.py` / `wordRules/index.js` | **docstring only** (Python); **delete** `index.js` (Node); every importer imports from the module that defines the name | −283 / −17 | none | py: `crowkis/privacy.py`, `turns/voice/{steps,call,turn}.py`, `turns/chat/turn.py`, `turns/values.py`, `rules/question/{context,urgent,shape,personal}.py`, `rules/save/{caller_specific,nothing_to_save}.py`, `rules/hit/hit.py`, `runtime/question_records.py`, `state/call_state.py`, `understanding/{rewrite_check,word_rule_classifier,fact_relevance,chat_details}.py`; tests `test_agent_voice`, `golden/build_inputs`, `test_voice_stress_bugs`, `test_voice_prompt_guard`, `understanding/test_word_rule_classifier`, `test_voice_stated_context`, `test_voice_rule_phrases`, `test_voice_identifiers`, `rules/fake_call`, `voice_turns_scenarios`, `test_voice_review_fixes`, `test_voice_rereview_fixes`, `test_voice_different_question`, `test_voice_crisis_and_structures`, `test_chat_prompt_guard`, `test_chat`, `conftest`. node: the 18 `wordRules/index.js` requires (`src/privacy.js`, `channels/voiceSession.js`, `rules/{hit/hit,question/{context,personal,shape,urgent},save/{callerSpecific,nothingToSave}}.js`, `runtime/questionRecords.js`, `state/callState.js`, `turns/{values,chat/turn,voice/{call,steps,turn}}.js`, `test-voice-stress-bugs.js`, `test/rules/fakeCall.js`, `test/understanding/wordRuleClassifier.test.js`) |
| 2 | **`channels/voice_session.py` imports 258 word-rule names "so `crowkis.channels.voice_session.<name>` keeps working" and uses 4.** Outside readers of the other 254: only `_words`, in `integrations/pipecat.py:89` (which re-exports it in turn) and `integrations/voice_turns.py:38`. No test imports or patches the rest (checked `from … import`, `module._x`, `setattr`). P5.6 already dropped the old module paths; these are private names. Node `voiceSession.js:~30-298`: 244 of 269 names unused (its `module.exports` lists only the ones it uses). | `channels/voice_session.py` / `channels/voiceSession.js` | **keep only the used names**; `pipecat.py` and `voice_turns.py` import `_words` from `word_rules.text` (`pipecat._words` stays importable) | −254 / −244 | none | py: `integrations/pipecat.py:89`, `integrations/voice_turns.py:38` |
| 3 | **`channels/call_session.py` re-exports 17 understanding names and uses none** (`chat_details` 12 of 13 unused, `frame_words` 2, `answer_patterns` 3), plus `_FUNCTION` from `rule_checker`, unused. Node `callSession.js`: 13 unused (`answerPatterns` 3, `chatDetails` 9, `frameWords` 1). | `channels/call_session.py` / `channels/callSession.js` | **delete the unused names** | −18 / −13 | none | — (no outside readers) |
| 4 | **`rules/rule_checker.py` re-exports 16 `frame_words` names and 2 `turn_frame` constants and uses none.** Node `ruleChecker.js`: 8 unused. | `rules/rule_checker.py` / `rules/ruleChecker.js` | **delete the unused names** | −18 / −8 | none | — (no outside readers) |
| 5 | **`FactRelevanceCheck` is a class for one method, and its one parameter (`confidence_floor`) is never passed.** Its two users (`StatedContextLost`, `StatedFactLost` in `rules/question/context.py:126,188`) take a `relevance` parameter that nobody passes either, in both languages. | `fact_relevance.py` / `factRelevance.js` | **make it a function** `stated_fact_irrelevant(stated, frame)` (helpers stay private); **delete** `confidence_floor` and the two `relevance` parameters | −8 / −8 | low | py: `rules/question/context.py:126,188`. node: `rules/question/context.js:136,205` |
| 6 | **`RewriteCheck` holds no state:** one method and two static helpers. One caller, `turns/voice/turn.py:103`, keeps a module-level instance. | `rewrite_check.py` / `rewriteCheck.js` | **make it a function** `accepted_rewrite(text, reading, rewritten, call)`, same body | −5 / −5 | low | py: `turns/voice/turn.py:10,103,108` (docstring). node: `turns/voice/turn.js` |
| 7 | **`BudgetedUnderstanding(fallback=…)`: nobody passes it**; the fallback is always `WordRuleClassifier()`. | `budgeted_understanding.py` / `budgetedUnderstanding.js` | **delete the parameter** | −1 / −1 | none | — |
| 8 | **`__all__` in `understanders.py` and `turn_frame.py`.** Nothing star-imports them, and the merge would have to combine them. | both / — | **delete** | −3 / 0 | none | — |
| | **Total** | | | **≈ −590 / −296** | | |

---

## Keep, and why

- **The four Protocols.** `Classifier` has four implementations (`WordRuleClassifier`, `LLMClassifier`,
  `TextOnlyClassifier`, `BudgetedUnderstanding`) plus the app's own. `Rewriter` has four (`NoRewrite`,
  `LLMRewriter`, `ReplayRewriter`, `BudgetedUnderstanding`). `Reading` has three (`WordReading`, `FrameReading`,
  `BudgetedReading`). `Understander` has three (`LLMUnderstander`, `ReplayUnderstander`, `WithFallback`). They are
  also the plug-in contract a customer codes against. Node has no Protocols (duck typing).
- **`BudgetedReading`.** It carries the rewrite made inside the same budget; it is not a forwarder.
- **`TextOnlyClassifier`** (Python only). It keeps a customer's P2-P4 `classify(text)` classifier working.
  Removing it is a public change. Node doesn't need it: a JS function ignores extra arguments.
- **`NoRewrite`.** It is the default slot. Without it, `turns/voice/turn.py` and `BudgetedUnderstanding` would each
  need a None check.
- **The public slot adapters and understanders:** `LLMClassifier`, `LLMRewriter`, `ReplayRewriter`,
  `ReplayUnderstander` (with `__len__`, which nothing in the repo calls, but which is public), `WithFallback` (with
  `primary_failures`, which `tests/test_understand.py:81` reads), `LLMUnderstander`, `TurnFrame` and its parts.
- **Look-alike helpers that behave differently.** Merging any of these would change decisions:
  - `_stem` exists three times: `frame_words` (suffix and "ic"/"e"/"y" trimming), `word_rules/text` (ies→y, keeps
    "ss"), and `RewriteCheck._stem` (lower case, drop a trailing "s").
  - `_normalise` exists twice: `understanders` turns inner punctuation into spaces; `word_rules/text` trims only
    the ends.
  - `_EMAIL` exists three times: `answer_patterns` `\S+@\S+`; `frame_words` adds "at gmail"; `word_rules/personal`
    is a character-class match. `_LONG_DIGITS` exists twice: answer `{5,}`, frame `{4,}`.
  - `_RELATIONS`, `_TITLES` and `_POSSESSIVE` in `chat_details` are different lists from `word_rules/text`'s
    `_RELATIONS`, `_TITLES` and `_POSSESSIVES`.
  - So the chat readers (`chat_details`, `frame_words`, `answer_patterns`) are not duplicates of `word_rules/`.
    They are Chat's own, separately tuned checks. They can share a file, but not code.
- **Python `chat_details._norm` and `word_rules.text._normalise` are identical** (strip edge ASCII punctuation and
  whitespace, lower case, single spaces), and so are the two `_TRIM` constants. **Node's twins are not:**
  `chatDetails.norm` strips any Unicode punctuation (`\p{P}`), and `wordRules/text.normalise` strips only ASCII.
  Merging would change Node's filler matching on text such as "¿hola?", so they stay apart. This is listed as a
  parity drift below, not changed.

## Only with a behaviour change (not done)

- **Node `norm` vs `normalise`:** make Chat's filler normaliser ASCII-only like Python's, then use one function in
  both languages. This changes Node decisions on edge Unicode punctuation. It needs the owner's call.

---

## Order of work (U1 step C)

1. **Deletions (risk none):** #1 to #4, #7, #8. Python and Node.
2. **Folds (failing-first tests where a signature changes):** #5 and #6. No test builds `FactRelevanceCheck` or
   `RewriteCheck` today. Add one each that calls the new function on the existing cases (it fails before, because
   the function doesn't exist yet).
3. **The move:** `understanding-layout-plan.md`.
4. **Frameworks** (Pipecat, LiveKit Py/JS, Bolna), `graphify update .`, and an Opus review.
