# T1: ponytail ultra pass over `turns/` (2026-11-04)

Read-only, at `fa67a47` (after C1). Scope: `python/crowkis/turns/` and `node/src/turns/` only. Nothing in the code
changed. Callers were counted with grep across `python/` (package, tests), `node/` (src, tests, `index.js`,
`index.mjs`, every `.d.ts`), `examples/` and the Bolna integration. `python/build/lib/` is a stale build copy and
was left out.

Starting point: `merge-check.md` §1 (2026-11-02). Every item there was re-checked against today's code. C1 moved
rules into `rules/<stage>/<category>.py` but did not touch `turns/`, so all 13 items still apply. Some importer
lists changed: `ChatTurn` is now imported by four `rules/question/*` files and `rule_checker`, and `ChatAnswer` by
two `rules/save/*` files. The pass then asked of every class, Protocol, function and parameter whether it needs to
exist at all.

**Hard limits kept.** No proposal changes a decision (golden files would stay identical). Every voice/chat step
pair that behaves differently stays apart. Every privacy check and error boundary keeps its handling. Public names
don't change: in Python, the `crowkis/__init__.py` exports (`Channel`, `VOICE`/`CHAT`/`REALTIME`, the seven route
constants, `TurnDecision`, `TurnResult`) and `crowkis.privacy` (which imports nothing from `turns`); in Node,
`index.js`, `index.mjs` and `index.d.ts` / `session.d.ts` / `voice.d.ts`. None of the names this report deletes
or moves is public.

**Risk:** *none* = types, docs or imports only; *low* = code moves between modules, or a class becomes a function
with the same body; *needs tests* = a signature or the async step count changes.

---

## Files and lines

| | Files before → after | Lines before → after (approx.) |
|---|---|---|
| Python `turns/` | 33 → 21 | 2,035 → ~1,695 (−340) |
| Node `turns/` | 31 → 20 | 1,813 → ~1,700 (−115) |

Python saves more because the 11 one-implementation Protocols and the `VoiceCall` Protocol exist only there. Node
uses duck typing and has no `voiceCall.js`.

---

## Ranked findings

Callers are listed as `py:` / `node:` paths relative to `python/crowkis/` and `node/src/`.

| # | Finding | Files (Python / Node) | Action | Lines saved (py / node) | Risk | Callers to repoint |
|---|---|---|---|---|---|---|
| 1 | **`VoiceCall` Protocol: 21 members, one implementation (`SessionCall`).** The test double `tests/rules/fake_call.py` is duck-typed and never imports it. Node never had it. | `voice_call.py` / — | **delete**; annotate with `SessionCall` | −80 / 0 | none | py: `turns/voice_turn.py:9,19`, `model_answer.py:9,19`, `voice_reader.py:12,23`, `voice_report.py:17,46`, `turns/__init__.py:9,13` (drop it from `__all__`), `understanding/rewrite_check.py:11,22` (TYPE_CHECKING). Docstring mentions: `session_call.py:1,30`, `chat_hit_check.py:27`, `tests/rules/fake_call.py:1` |
| 2 | **Ten "what X reads of the session" Protocols, each with one implementation and no reader outside its own file:** `ChatSessionHooks`, `ChatSessionSaves`, `ChatSessionUnderstanding`, `ChatSessionReports`, `ChatSessionChecks`, `ChatSessionAppHooks`, `ChatSessionBudget`, `ChatSessionState`, `VoiceSessionSaves`, and `VoiceSessionTranscript` (defined twice, in `voice_pairing.py:16` and `voice_report.py:29`). Node has none of them. | 10 files / — | **delete**; type `session` as `"CallSession"` / `"VoiceSession"` under `TYPE_CHECKING` | −98 / 0 | none | only the annotation in each file's own `__init__` |
| 3 | **`AppHooks` is a class that holds only `session` and wraps three hook calls in try/except.** It can be one function: `_call_hook(hook, *args)` returns the hook's result, or None when the hook raises. All three uses keep the same boundary: urgent ignores the result, tools treats None as "the model answers", event ignores it. Node's `urgent`/`tools` take a `then` continuation so that a turn with a hook takes no extra async step. | `app_hooks.py` / `appHooks.js` | **make a function** in `chat_answers` (Python `call_session.emit` imports it); in Node, a sync `callHook` for `event` and an inline `try { await … }` in `chatAnswers._urgent` / `_tools` that keeps the `then` shape | −37 / −20 | py low; **node needs tests** (step ordering: `test/turns/recordThenDecide.test.js`) | py: `channels/call_session.py:41,177` (construction), `:230` (`.event`); `turns/chat_answers.py:10,45,80,91`. node: `channels/callSession.js:23,117`; `turns/chatAnswers.js` |
| 4 | **`VoicePairing` only forwards to `TurnPairing`.** `open()` is `begin()` + `start(len(transcript))`; `settle()` wraps `TurnPairing.settle` in a `Checked`. Fold both into `TurnPairing`, rename its current `settle(turn)` to `settle_turn`, and move `INTERRUPTED` with it. (merge-check #2) | `voice_pairing.py` / `voicePairing.js` → `runtime/turn_pairing` | **fold into `TurnPairing`** | −28 / −25 | needs tests | py: `channels/voice_session.py:24,629`; `tests/runtime/test_turn_pairing.py:13,21,29,40` (`settle` → `settle_turn`). node: `channels/voiceSession.js:14,593`; the matching `test/runtime` test |
| 5 | **`ChatUnderstanding` has one user, `ChatReader`, and the two are always built together** (`ChatReader(self, ChatUnderstanding(self, _UNDERSTAND))`). It is the read step's error boundary, so its methods move into `ChatReader` unchanged (`frame` → `_frame`; `pool` becomes `ChatReader`'s parameter). No test builds or patches it. | `chat_understanding.py` / `chatUnderstanding.js` → `chat_reader` | **fold the class into `ChatReader`** | −20 / −12 | low | py: `channels/call_session.py:46,190`. node: `channels/callSession.js:20,133`. Node's `chatUnderstanding.js` imports `isThenable` from `turnCore.js`; `chatReader.js` will import it instead |
| 6 | **`ChatReading` is only what `ChatReader.read` returns.** (merge-check #10) | `chat_reading.py` / `chatReading.js` → `chat_reader` | **merge file** | −8 / −6 | low | py: `channels/call_session.py:47`; `turns/chat_question_check.py:12`. node: `channels/callSession.js:21` |
| 7 | **The `turn_steps` interfaces are read only by `turn_core`.** They stay, because each has two real implementations and they are the core's contract. **`Report.refused` comes out:** the core never calls it (only `voice_saving` / `chat_saving` call their concrete report's `refused`). (merge-check #3) | `turn_steps.py` / `turnSteps.js` → `turn_core` | **merge file; delete `Report.refused`** | −11 / −8 | none | py: `turns/turn_core.py:11`. node: the JSDoc `import("./turnSteps.js")` types in `turnCore.js` |
| 8 | **`Checked`/`LookedUp` and `Outcome`/`RecordedOutcome` exist to carry a `Verdict`.** (merge-check #4, #5) | `checked.py`, `outcome.py` / `checked.js`, `outcome.js` → `verdict` | **merge files** | −16 / −8 | low | py: `Checked` 10 importers, `LookedUp` 4, `Outcome` 11 (`channels/voice_session.py:20,21`, `runtime/bounded_writer.py:9`, `turns/*`, and two `rules/save` files through `turns/__init__`). node: `rules/ruleSet.js:17`; `OUTCOME` in `channels/voiceSession.js:11`, `rules/save/{callerSpecific,nothingToSave}.js:5`, `runtime/boundedWriter.js:3` |
| 9 | **The two voice rule subjects (`VoiceTurn`, `ModelAnswer`) both hold the call.** Node's two files each define the same `_once` memo helper; merging leaves one. (merge-check #9) | `model_answer.py` / `modelAnswer.js` → `voice_turn` | **merge file** | −8 / −14 | low | py: `turns/__init__.py:5`, `voice_saving.py:26`; rules import it through `turns/__init__` (unchanged). node: `turns/voiceSaving.js` |
| 10 | **The two chat rule subjects (`ChatTurn`, `ChatAnswer`).** (merge-check #8) Node `channels/callSession.js:51,52` imports both and uses neither. | `chat_answer.py` / `chatAnswer.js` → `chat_turn` | **merge file** | −8 / −4 | low | py: `rules/save/caller_specific.py:10`, `rules/save/nothing_to_save.py:9`, `turns/chat_saving.py:14`, `tests/rules/test_stage_rules.py:12`. node: `turns/chatSaving.js`, plus the two dead imports (a one-line follow-up outside `turns/`) |
| 11 | **`Hit` is what `CachedAnswer` wraps.** (merge-check #6) | `hit.py` / `hit.js` → `cached_answer` | **merge file** | −8 / −4 | low | py: `rules/hit/hit.py:10`, `rules/rule_set.py:10`, `turns/chat_hit_check.py:11`, `tests/rules/test_stage_rules.py:15`. node: `rules/ruleSet.js:18`, `turns/chatHitCheck.js` |
| 12 | **`routes.py` is a 4-line file of constants that `turn_result` already imports.** The public names don't change: the root re-imports them from the new module. It has 17 import sites, so this is the most edits for the fewest lines saved. (merge-check #7) | `routes.py` / `routes.js` → `turn_result` | **merge file** (optional) | −3 / −3 | low | py: `crowkis/__init__.py:34`, `channels/call_session.py:52`, `rules/question/shape.py:11`, `rules/question/urgent.py:8`, `rules/rule_checker.py:32`, `turns/chat_answers.py:13`, `chat_question_check.py:15`, `chat_report.py:12`, `chat_saving.py:18`; tests `test_chat_hit_guards.py:10`, `test_session.py:10,14`, `test_understand.py:11`, `test_verify.py:10`. node: `index.js:1354`, `channels/callSession.js:27`, `rules/question/{shape,urgent}.js`, `rules/ruleChecker.js:15` |
| 13 | **`TurnCore._outcome` is a private method with one caller (`record`).** Node already inlines it. | `turn_core.py` / — | **fold into `record`** | −4 / 0 | none | — |
| 14 | **`ModelAnswer.keyed()` rebuilds the whole object to set one field.** Its one caller (`VoiceSaving.check`) owns the object, and no cached property depends on `key`. | `model_answer.py` / `modelAnswer.js` | **delete**; `answer.key = …` | −4 / −4 | low | py: `turns/voice_saving.py:76`. node: `turns/voiceSaving.js` (`_keyed`) |
| 15 | **`VoiceReader`'s `rewrite_check` parameter: the only caller always passes `RewriteCheck()`**, which holds no state. The check stays as it is (a privacy spec); only the parameter goes. | `voice_reader.py` / `voiceReader.js` | **delete the parameter**; call `RewriteCheck().accept` (or a module-level instance) inside | −3 / −3 | none | py: `channels/voice_session.py:625`. node: `channels/voiceSession.js:585` |
| 16 | **`SAVE_REFUSED = "save_refused"` is defined twice** (chat report and chat saving), in both languages. | `chat_saving.py` / `chatSaving.js` | **delete**; import it from `chat_report` | −1 / −1 | none | — |
| 17 | **The budget-left sum is written twice:** `None if budget is None else budget - spent` before `QuestionRecords.answers_another_question`, in `SessionCall.answers_another_question` and in `ChatHitCall.answers_another_question`. | `session_call.py`, `chat_hit_check.py` / twins | **fix once**: `QuestionRecords.answers_another_question` takes `budget_ms, spent_ms` | −3 / −3 | low (`runtime/question_records` changes too) | the two methods above |
| | **Total** | | | **≈ −340 / −115** | | |

---

## Keep, and why

- **`TurnCore` and all 8 of its slots.** Each slot is filled differently for voice and chat (checked at both
  construction sites, `voice_session.py:629` and `call_session.py:189`, and the Node twins). `cache_lookup` too:
  chat builds `CacheLookup(refuse_late_hits=False, deadline_counts=…, unavailable_counts=…)`, voice uses the
  defaults. `settings` (`CallSettings`) has two implementations. Voice passes one object for two slots
  (`VoiceReport` is both `answers` and `report`; the `RuleSet` is both `question_check` and `hit_check`). That is
  fine.
- **`TurnCore.look_up` / `lookUp`.** `CallSession._lookup` calls it (`call_session.py:234`,
  `callSession.js:168`). Node's `decide` inlines the same steps on purpose (no extra await).
- **Every voice/chat step pair**: pairing, early answers, reader, question check, hit check, report, saving. The
  table in `merge-check.md` §1a still holds after C1. Merging them is the owner's separate "option b".
- **`VoiceReport.before_reading`**, which always returns None. It fills a real slot; removing it would mean a
  None-check in the core instead.
- **`SessionCall`, including its 14 one-line forwarders.** It is the rules' only view of the call: rules never
  reach into the session, and `mark_tainted` is the one write. Folding it into `VoiceSession` would add its
  methods (`chain`, `context_key`, …) to a public class. Node's extra `hasValues` getter is a parity drift (Python
  reads `call.values` truthiness, which an empty `{}` gets wrong in JS). Keep it.
- **`ChatHitCall` + `ChatHitTurn`.** The hit rules read `turn.call.commitments` / `answers_another_question`,
  `turn.key` and `turn.is_personal`. The two small adapters are what let the voice hit rules run on a chat hit.
  Separate check, not done here: `rules/hit/hit.py` also reads `call.serve_above` and `call.channel`, which
  `ChatHitCall` lacks. That is only safe if `ChatRuleSet.hit_chain()` never includes those rules.
- **`ChatTurns`, `ChatQuestionCheck`, `ChatHitCheck`, `ChatReport`, `ChatSaving`, `VoiceReader`, `VoiceSaving`
  as classes.** Each fills a `TurnCore` slot and holds its collaborators. Making them functions would mean
  changing the core's slots to callables: a redesign, not a deletion.
- **`Channel` and its unread fields** `isolates_context`, `audio`, `saves_answers`. Nothing reads them in either
  language, but `Channel` is public (root export, `index.d.ts:562-587`). Its constructor takes them, and
  `tests/turns/test_channel_profiles.py:25` builds one with all of them. Removing them is a public change: the
  owner's call, not this pass.
- **`Outcome.__str__` / `__format__`**, so the `str` enum prints its word on every Python version.
  **`RecordedOutcome`** is what `decision.stored` / the adapters compare. Node returns plain objects instead (an
  existing parity difference).
- **`TurnDecision`, `TurnResult`, `Channel`, `answered.py`, `decision.py`, `cached_answer.py`, `verdict.py`**: public
  or shared value types.
- **The user-turn filter over the transcript, written four times** (`session_call.py:108,122,150`,
  `voice_saving.py:136`, and the Node twins). A helper would save no lines, and each use differs (`or ""`,
  `[:-1]`, a reversed loop). Leave it.
- **`turns/__init__.py`**. After #1 it still exports what `rules/` imports through the package (`Verdict`,
  `VoiceTurn`, `ModelAnswer`, `CachedAnswer`, `Outcome`, `SessionCall`).

---

## Order of work for the follow-up session

Do Python and Node together, step by step. Run the full suites after each step; golden files must stay identical.

1. **Types only (risk none):** #2 (delete the ten session Protocols), #1 (`VoiceCall`), #7's `Report.refused`,
   #16, #13. Python only, except #16.
2. **Mechanical file merges (Sonnet low):** #8 (`checked`, `outcome` → `verdict`), #11, #9, #10, #6, #7
   (`turn_steps` → `turn_core`), then #12 if the owner wants it. Repoint imports, run the suites, then
   `graphify update .`.
3. **Class folds (Sonnet normal):** #5 (`ChatUnderstanding` into `ChatReader`), #14, #15, #17.
4. **Needs tests (Sonnet normal, Opus review):** #4 (`VoicePairing` into `TurnPairing`; rename `settle` →
   `settle_turn`) and #3 (`AppHooks` → a function; the Node step ordering is checked by `recordThenDecide`, plus
   a failing-hook test for each of urgent, tools and event).
5. Frameworks (Pipecat, LiveKit Py/JS, Bolna) once at the end: every change above is internal to `turns/` and the
   two channel facades, so the adapters only re-import.

Outside `turns/`, for the cleanup list, not this pass: Node `channels/callSession.js:51,52` dead imports
(`ChatAnswer`, `ChatTurn`); `channels/voice_session.py:21`'s unused `RecordedOutcome as _Outcome` (also
`merge-check.md` §2).
