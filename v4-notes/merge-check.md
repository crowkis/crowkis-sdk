# Merge check: which files in `python/crowkis/` can be merged (2026-11-02)

Read-only, at `7a78596` (after F1, F2, F3). Nothing changed, nothing committed. Callers found with grep, with
`graphify update .` run first. Node (`node/src/`) was not read file by file. Each Python merge below has a Node twin
(`node/src/turns` has 31 files; there is no `voiceCall.js`, only a typedef), and parity means doing both together.

Tests used: two files that always change together, one file used only by the other, or a file too small to earn its
place (a lone type, a forwarder, a Protocol with one implementation) → merge. Files that change for different
reasons, or a voice/chat pair that behaves differently → keep apart. Owner decisions respected: one rule per file in
`rules/<stage>/`, one turn core, public names unchanged (`crowkis/__init__.py` exports, `crowkis.privacy`). No
internal module path (`crowkis.turns.*`, `crowkis.understanding.*`, ...) is named in any README or doc, and v4 has
never been released, so moving a class between internal modules only means editing imports.

Line savings are estimates. A merge saves the moved file's docstring, `from __future__`, repeated imports and blank
lines (about 8 lines); deleting a Protocol saves its whole body.

**Risk:**
- **none:** types or imports only; the suites and the golden files can't change.
- **low:** imports move between modules; watch for import cycles (each one below was checked by hand).
- **needs tests:** a method is renamed or a signature changes.

---

## Summary

| Folder | Files now → after | Lines now → after (approx.) |
|---|---|---|
| `turns/` | 33 → 21 | 2,032 → ~1,740 |
| `channels/` | 6 → 6 | 2,134 → ~1,830 |
| `understanding/` (top level) | 17 → 10 | 1,038 → ~985 |
| `understanding/word_rules/` | 11 → 11 | 2,884 → 2,884 |
| `rules/` (all stages) | 62 → 60 | 1,939 → ~1,925 |
| `runtime/` | 9 → 8 | 505 → ~510 (gains `VoicePairing`) |
| `state/` | 2 → 2 | 322 |
| `keys/` | 2 → 2 | 88 |
| `integrations/` (incl. `bolna/`) | 10 → 10 | 2,728 |
| package root | 8 → 8 | 3,389 |
| **Total** | **160 → 138 (−22)** | **17,059 → ~16,400 (about −660, −4%)** |

Most of the lines saved come from two deletions, not from merges: the facades' re-export blocks (about −285) and the
one-implementation Protocols, `VoiceCall` included (about −180). The merges mostly cut the file count. The package's
size is still in `client.py` (2,158), `word_rules/` (2,884) and `voice_session.py`. Merging files doesn't shrink those.

---

## 1. `turns/` (33 → 21 files)

### 1a. The voice/chat pairs, side by side

Every step pair was re-read against today's code. None of them differs only by a setting, so **no pair is merged
into one class**. Where each half of a pair sits next to a value type that only it uses, that type moves into the
half's file (section 1b).

| Step (`TurnCore` slot) | Voice | Chat | Verdict | Why |
|---|---|---|---|---|
| Pairing | `voice_pairing.VoicePairing` (42) over `runtime.TurnPairing` | `chat_turns.ChatTurns` (55) | **keep apart** | Voice numbers turns under one lock shared with barge-in (`cancel(trim)`), keys turns by transcript mark, and drops a late answer as `Interrupted`. Chat tracks the one turn awaiting an answer and a set of cancelled turns (`Cancelled` / `Stale`). `VoicePairing` itself goes into `TurnPairing` (1b #2). |
| EarlyAnswers | `VoiceReport.before_reading` / `after_check` | `chat_answers.ChatAnswers` (97) | **keep apart** | Voice has one early answer (a filler rule's verdict). Chat has empty turns, fillers, sharing off, the urgent hook and script, and `on_tools`. |
| TurnReader | `voice_reader.VoiceReader` (37) | `chat_reader.ChatReader` (47) | **keep apart** | Voice: the classifier and rewriter slots plus `RewriteCheck`, notes the reading. Chat: the understander's frame, then notes what was told, names, IDs and the language. |
| QuestionCheck | `rules.RuleSet.check_question` | `chat_question_check.ChatQuestionCheck` (67) | **keep apart** | Chat runs `RuleChecker` V1–V10, then the shared-question rules and the urgent words, and updates the state. Voice runs one chain. |
| HitCheck | `rules.RuleSet.check_hit` | `chat_hit_check.ChatHitCheck` (72) | **keep apart** | Chat stops an unconfident hit before its rules and doesn't count it, then counts a refusal by the rule's name. Voice counts by `Counter`. |
| Report | `voice_report.VoiceReport` (157) | `chat_report.ChatReport` (106) | **keep apart** | `TurnDecision` + `Stats` + the transcript + audio vs `TurnResult` + `counts` + events. |
| Saving | `voice_saving.VoiceSaving` (150) | `chat_saving.ChatSaving` (84) | **keep apart** | Voice: answer-given rules, then the transcript, the personal template path and `last_stored`. Chat: notes the reply, shares only a shared question's answer. |
| Question-rule subject | `voice_turn.VoiceTurn` (68) | `chat_turn.ChatTurn` (20) | **keep apart as classes** | Different fields (`call`, `reading`, `rewritten` vs `frame`, `state`). The rules read them differently. |
| Save-rule subject | `model_answer.ModelAnswer` (43) | `chat_answer.ChatAnswer` (25) | **keep apart as classes** | Same reason. The save-rule twins depend on this (audit finding 6 still holds). |
| Answer handed to `record()` | `answered.VoiceAnswered` | `answered.ChatAnswered` | **already one file, keep** | 39 lines, both halves of one idea. |
| Result | `decision.TurnDecision` (78, public) | `turn_result.TurnResult` (27, public) | **keep apart** | Both public, different fields and behaviour. |

### 1b. Proposed merges in `turns/`

| # | Files | → Target | Why | Lines saved | Risk |
|---|---|---|---|---|---|
| 1 | `voice_call.py` (83) | **delete**; type with `SessionCall` under `TYPE_CHECKING` | A 22-member Protocol with one implementation. `tests/rules/fake_call.py` is duck-typed and doesn't import it. Importers: `voice_turn`, `model_answer`, `voice_reader`, `voice_report`, `turns/__init__`, `understanding/rewrite_check` (type-only). F2 kept it "because the types name it"; that is only a rename of 6 annotations. | ~−78 | none |
| 2 | `voice_pairing.py` (42) | `runtime/turn_pairing.py` | An adapter over a class only voice uses. `open()` = `begin()` + `start()`. `settle()` wraps `TurnPairing.settle` in a `Checked`. Rename the existing `TurnPairing.settle(turn)` to `settle_turn` (callers: `voice_pairing`, `voice_session`). | ~−28 | needs tests |
| 3 | `turn_steps.py` (99) | `turn_core.py` | Only `turn_core` imports it, and the step interfaces change whenever the core's steps do. These Protocols stay: each has two real implementations. Still one turn core. | ~−8 | low |
| 4 | `checked.py` (28) | `verdict.py` | `Checked` / `LookedUp` carry a `Verdict`. `verdict.py` keeps its ~40 importers; the 12 importers of `checked` change. | ~−8 | low |
| 5 | `outcome.py` (50) | `verdict.py` | `Verdict.outcome` is an `Outcome`. `Outcome` and `RecordedOutcome` change with the verdicts that carry them. No imports of its own, so no cycle (`runtime/bounded_writer` imports both). | ~−8 | low |
| 6 | `hit.py` (34) | `cached_answer.py` | `CachedAnswer` wraps a `Hit`; both are "what the cache returned". Importers: `rules/rule_set`, `rules/chat_rule_set`, `rules/hit/commitment_policy`, `chat_hit_check`, a test. | ~−8 | low |
| 7 | `routes.py` (4) | `turn_result.py` | A 4-line file of constants that `TurnResult` already imports. Public names unchanged: the root re-imports them from `turns.turn_result`. 15 importers (rules, the root, 4 tests). | ~−4 | low |
| 8 | `chat_answer.py` (25) | `chat_turn.py` | The two subjects Chat's rules read. Both are tiny value classes over `CallState` / `TurnFrame`. 10 importers (save rules, `chat_saving`, a test). | ~−8 | low |
| 9 | `model_answer.py` (43) | `voice_turn.py` | The two subjects voice's rules read; both hold the call. Rules import `ModelAnswer` through `turns/__init__`, so only `__init__` and `voice_saving` change. | ~−8 | low |
| 10 | `chat_reading.py` (40) | `chat_reader.py` | `ChatReading` is what `ChatReader.read` returns. Importers: `chat_reader`, `chat_question_check`, `call_session`. | ~−8 | low |
| 11 | `chat_understanding.py` (76) | `chat_reader.py` | Only `ChatReader` uses `ChatUnderstanding` (`call_session` only builds it). It is the read step's error boundary. | ~−8 | low |
| 12 | `app_hooks.py` (45) | `chat_answers.py` | `AppHooks` is used only by `ChatAnswers` (and built in `call_session`, which also calls `.event`). Its `ChatSessionAppHooks` Protocol goes (item 13). | ~−8 | low |
| 13 | One-implementation Protocols, in the files that remain: `ChatSessionHooks` (18), `ChatSessionSaves` (13), `ChatSessionUnderstanding` (11), `VoiceSessionSaves` (11), `ChatSessionReports` (10), `ChatSessionChecks` (9), `ChatSessionAppHooks` (8), `ChatSessionBudget` (6), `ChatSessionState` (6), `VoiceSessionTranscript` (6, defined twice: `voice_pairing`, `voice_report`) | **delete**; type `session` as `"CallSession"` / `"VoiceSession"` under `TYPE_CHECKING` | Each has exactly one implementation. No test uses them. `CallSettings` stays: both sessions implement it. | ~−98 | none |

Kept as files: `turn_core`, `session_call` (161, real logic: chain, `after_urgent`, keys, `engine_vouches`),
`decision`, `turn_result`, `channel` (public), `answered`, `verdict`, `cached_answer`, the 7 step pairs above, and
`chat_turns`. That is 21 files, with `__init__.py`.

**`turns/` after (21):** `__init__`, `answered`, `cached_answer` (+hit), `channel`, `chat_answers` (+app_hooks),
`chat_hit_check`, `chat_question_check`, `chat_reader` (+chat_reading, +chat_understanding), `chat_report`,
`chat_saving`, `chat_turn` (+chat_answer), `chat_turns`, `decision`, `session_call`, `turn_core` (+turn_steps),
`turn_result` (+routes), `verdict` (+checked, +outcome), `voice_reader`, `voice_report`, `voice_saving`, `voice_turn`
(+model_answer).

Not proposed: merging `voice_reader` into `voice_turn`. That would leave the two readers asymmetric and pull
`rewrite_check` and `slots` into a module the rules import. Also not proposed: `decision` into `voice_report`, which
would put the public `TurnDecision` inside a step file.

---

## 2. `channels/` (6 → 6 files; about −305 lines)

No file merges. `voice_session` / `async_voice_session` / `realtime` / `call_session` / `chat` are public facades
with different jobs (`Chat` wraps `CallSession` and both are public).

### Re-export blocks: what can go

**`channels/voice_session.py`** (1,118 lines):

| Lines | What | Verdict |
|---|---|---|
| 38–297 | 258 private `word_rules` names, "re-exported so `crowkis.channels.voice_session.<name>` keeps working" | **Delete.** Keep importing only the 4 the facade uses itself: `_COMMITMENTS`, `_carries_call_context`, `_normalise`, `_sets_context`. Keeping `_sets_context` imported by name keeps the mock target `crowkis.channels.voice_session._sets_context` (`tests/test_voice_undecided_turns.py:107`) working, because `voice_session` looks the name up itself. |
| 21 | `RecordedOutcome as _Outcome` "(old name)" | **Delete.** Nothing reads `_Outcome`. |
| 306–309 | `_QUESTIONS_KEPT`, `_QUESTION_TTL`, `_question_key`, `_tenant_of` aliases "(names kept here)" | **Delete**, and trim the import on line 35. No reader anywhere. |
| ~311–328 | Comment blocks with no code under them ("Turns whose answer must never be shared", the system-prompt guard explanation). The code moved to `word_rules/prompt_details.py`. | **Delete** (or move the guard comment into `prompt_details.py` if it isn't already there). |
| 345–347 | `_PENDING_WRITES`, `_submit_write`, `_wait_for_writes` | **Keep.** `_wait_for_writes` is imported by 6 test files and `tests/conformance.py`; `_submit_write` by `call_session`, `question_records` and `session_call`; `_PENDING_WRITES` by `test_voice_slow_writes.py`. |

Facade importers to repoint: `integrations/voice_turns.py:38` and `integrations/pipecat.py:89` (`_words`) →
`understanding.word_rules`. `pipecat.py` says `_words` is "kept importable from here"; grep finds no reader of
`pipecat._words`, so drop that comment too. `understanding/word_rules/__init__.py:3`'s docstring names the facade
path; fix the docstring. About −275 lines.

**`channels/call_session.py`** (298 lines):

| Lines | What | Verdict |
|---|---|---|
| 54–68 | 13 `chat_details` names "re-exported" | **Delete all but `_norm`** (the only one used). |
| 69 | `_CALENDAR`, `_DAYS` (`frame_words`) | **Delete.** Unused, no readers. |
| 70 | `_ACTION_CLAIM`, `_EMAIL`, `_LONG_DIGITS` (`answer_patterns`) | **Delete.** Unused, no readers. |
| 71 | `from .voice_session import _PII_PLACEHOLDER, _instructs, _proper_nouns, _tells_about_caller, _words` | **Delete.** None is used in `call_session` and nothing reads them through it. Also removes `call_session`'s dependency on the voice facade. |
| 52 | `FILLER` "re-exported" | **Delete.** The root imports `FILLER` from `turns.routes`; nothing reads it here. |
| 53 | `TurnResult` "re-exported" | **Keep.** The root does `from .channels.call_session import CallSession, TurnResult`, and tests may too. |
| 74 | `_FUNCTION` from `rule_checker` | **Delete.** Imported, never used, and nothing reads it through the facade. |

About −22 lines. The audit's request still stands for both blocks: confirm with the owner that `crowkis.channels.*`
has never been published. `feat/v4` is not pushed, and P5.6 already removed the old paths under an owner exception.

---

## 3. `rules/` (62 → 60 files)

One rule per file in `rules/<stage>/` stays: no rule file merges, and the voice/chat save twins stay (audit finding
6: their names, reasons and counters are public behaviour). `rule_set.py` (voice `RuleSet`, public) and
`chat_rule_set.py` (Chat's chains) are a real pair: keep. `rule_checker.py` is public (`RuleChecker`, `Verdict`):
keep. The stage `__init__.py` files are the public lists: keep.

| # | Files | → Target | Why | Lines saved | Risk |
|---|---|---|---|---|---|
| 1 | `hit/commitment_policy.py` (14) | `hit/commitment_rewording.py` | Not a rule: a 3-entry table used only by `CommitmentRewording`. (Audit finding 7 goes further: replace it with the one `_COMMITMENTS` table. That is a logic change, not a merge.) | ~−7 | low |
| 2 | `rule.py` (35) | `chain.py` | The three stage interfaces (these do have many implementations) and the chain that runs them change together. Public via `rules/__init__`, unchanged. | ~−6 | low (optional) |

---

## 4. `runtime/` (9 → 8 files)

| # | Files | → Target | Why | Lines saved | Risk |
|---|---|---|---|---|---|
| 1 | `write_result.py` (32) | `bounded_writer.py` | `WriteResult` is what `BoundedWriter.write_within` returns. Importers: `bounded_writer`, `voice_saving`. | ~−8 | low |
| — | `turns/voice_pairing.py` in | `turn_pairing.py` | See `turns/` #2. | (counted there) | needs tests |

Kept: `deadline.py` (22, shared by `cache_lookup`, `question_records`, `session_call` and `chat_understanding`; a
helper with 4 callers earns its file), `cache_lookup`, `question_records`, `stats`, and `write_workers` (thread
machinery, also used directly by `voice_session`; it changes for a different reason than the bounded-write policy).

---

## 5. `understanding/` (17 → 10 files at the top level; `word_rules/` 11 → 11)

| # | Files | → Target | Why | Lines saved | Risk |
|---|---|---|---|---|---|
| 1 | `word_rule_classifier.py` (37), `no_rewrite.py` (13), `text_only_classifier.py` (33) | `slots.py` | The slot interfaces plus their default fillers and the adapter that fits an old classifier into the slot. All small, all read with the slots. Cycle check: `slots` would import `word_rules`, which imports nothing from `state` or `understanding.slots` (`state/call_state.py` already imports both). | ~−20 | low |
| 2 | `llm_classifier.py` (23), `llm_rewriter.py` (27), `replay_rewriter.py` (29) | `understanders.py` | Adapters from an `Understander` to the two slots; they import only `understanders`, `frame_reading` and `call_state`. Public names unchanged; the root's three import lines change. Cycle check: `understanders` → `frame_reading` → `turn_frame`, no way back. | ~−20 | low |
| 3 | `answer_patterns.py` (13) | `chat_details.py` | Three regexes. Its users are `chat_details` and 3 save rules (and `call_session`'s re-export, deleted above). Don't put them in `word_rules/answers.py`: `word_rules` has its own `_EMAIL`, so the names would clash. | ~−6 | low |

Kept: `turn_frame` and `understanders` (both public), `frame_reading` (`CONFIDENCE_FLOOR` is also read by
`fact_relevance`; see audit finding 7: `rule_checker` still repeats 0.6), `fact_relevance`, `frame_words`,
`chat_details`, `budgeted_understanding`, `rewrite_check` (a privacy spec; its only user is `VoiceReader`, but it
changes for privacy reasons, not reading ones), and `__init__`.

**`word_rules/`: no merges.** Theme modules from 70 to 772 lines; the cost there is long functions (cognitive
complexity up to 80), not file count. `word_rules/__init__.py` is 285 lines of pure re-exports (no functions). It is
the package's interface: about 40 modules import `from ..understanding.word_rules import _x`, and `crowkis.privacy`
reads it. Keep it. Once the `voice_session` block goes, it is the only copy of that list.

---

## 6. `state/`, `keys/`, `integrations/`, the root: no merges

- **`state/`** (`call_state.py` 321 + `__init__`): one module, made in F2. Keep.
- **`keys/`** (`knowledge_segment.py` 83 + a 5-line `__init__`): one module in its own folder. It could fold into
  `keys/__init__.py` (−1 file), but F2 just created this place and the owner keeps folders. Keep.
- **`integrations/`**: `bolna/` is 4 files of 154–398 lines, each with one job (registration, LLM wrapper, turn
  filter, synthesizer); `turn_filter` is used by `llm` and `__init__`. Balanced: keep. `voice_turns.py` (535) is the
  shared adapter layer for Pipecat (and the Node twin), `pipecat` / `livekit` / `langchain` / `memory` are separate
  frameworks. Keep all. Only edit: the `_words` import (section 2).
- **Root**: `client` (2,158), `agent`, `grpc_stub`, `openai_wrapper`, `_config`, `_help`, `privacy` (16, a public
  path), `__init__`. All public or separate concerns. Keep.

---

## 7. The earlier audit (`ponytail-audit.md`, `76239da`) against today

| Audit finding | Today |
|---|---|
| 1 deadlines not cancelled | **Fixed.** `runtime/deadline.within` cancels queued work. `cache_lookup`, `question_records` and `session_call.engine_vouches` call it. `budgeted_understanding.py:82` still waits by hand but cancels (as the audit said). |
| 2 facade re-exports | **Still there**: 258 + about 20 names. Section 2. |
| 3 eleven one-implementation Protocols | **Still there**, 104 lines (`VoiceSessionTranscript` still defined twice). `turns/` #13. |
| 4 `VoiceCall` | **Still there.** F2 moved `tainted` / `heard` into `CallState`, so `SessionCall` no longer writes the session's private fields (the intimacy is gone). The forwarders and the one-implementation Protocol remain. `turns/` #1. |
| 5 `TurnResult` hints crash | **Fixed** (`verdict: Optional[Any]`). |
| 6 save twins | Unchanged; still keep them. |
| 7 duplicates | **Still there**: `rule_checker.py:85` `confidence_floor=0.6` vs `CONFIDENCE_FLOOR`; `commitment_policy` vs `_COMMITMENTS`; the tenant `getattr` chain in 3 places (`question_records.py:29`, `session_call.py:156`, `call_session.py:271`). Not merges; a small follow-up. |
| 8 `str(error)` in logs | **Still there** at `turns/voice_report.py:101` (`refused`). Owner's go needed. |
| 9 `VoicePairing` | **Still there.** `turns/` #2. |
| 10 hit typed once | **Still there**: `chat_hit_check` reads `hit.get("route")`, `voice_report` reads `looked.hit["confidence"]`, `chat_report` reads `looked.hit["answer"]`. |
| 11 `Report.refused` in the Protocol | **Still there** (`turn_steps.py`). Drop it when `turn_steps` merges into `turn_core`. |
| `understanding/call_readings.py` | **Gone** (F2, into `CallState`). |

---

## 8. Order to do it in (safest and biggest first)

Each step is its own commit, in Python and Node together. The bar after each one: the full suites twice, golden
decisions identical (nothing here may change a decision), the three frameworks and Bolna for steps 1 and 7, and an
import smoke test (`python -c "import crowkis, crowkis.integrations.pipecat"` with the extras).

1. **Delete the re-export blocks** in `voice_session.py` / `call_session.py`, plus the dead aliases and orphan
   comments; repoint `_words` in `pipecat.py` / `voice_turns.py`. About −300 lines, 0 files. Risk: low. *Owner:
   confirm `crowkis.channels.*` never shipped.*
2. **Delete the one-implementation Protocols and `VoiceCall`**; type with `"VoiceSession"` / `"CallSession"` /
   `"SessionCall"` under `TYPE_CHECKING`. About −180 lines, −1 file. Risk: none (types only).
3. **Merge the `turns/` value types**: `checked` + `outcome` → `verdict`; `hit` → `cached_answer`; `routes` →
   `turn_result`; `chat_answer` → `chat_turn`; `model_answer` → `voice_turn`. −6 files, about −45 lines. Risk: low
   (imports only).
4. **Merge the `turns/` step helpers**: `turn_steps` → `turn_core` (drop `Report.refused`); `app_hooks` →
   `chat_answers`; `chat_reading` + `chat_understanding` → `chat_reader`. −4 files, about −32 lines. Risk: low.
5. **Merge the `understanding/` slot files**: 3 → `slots`, 3 → `understanders`, `answer_patterns` → `chat_details`.
   −7 files, about −46 lines. Risk: low (root import lines; run the import smoke test).
6. **`rules/` and `runtime/` small ones**: `commitment_policy` → `commitment_rewording`; `rule` → `chain`
   (optional); `write_result` → `bounded_writer`. −3 files, about −21 lines. Risk: low.
7. **`VoicePairing` into `TurnPairing`** (rename `TurnPairing.settle` → `settle_turn`). −1 file, about −28 lines.
   Risk: needs tests (barge-in and late-answer tests, all three frameworks, Bolna).

Total: **−22 files, about −660 lines** (160 → 138 files, 17,059 → ~16,400 lines). Python only; Node mirrors it.

**Not done here, and not merges:** audit findings 7, 8 and 10 (duplicate floor / table / tenant chain, the log line,
the typed `Hit`). They are small, separate fixes. `client.py` and the word-rule long functions are where the real
size is; per the audit, change them only when a fix touches them.
