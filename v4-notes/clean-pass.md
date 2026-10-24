# P5.5 clean-code pass

Plan: `../sdk-docs/v4-refactor-plan.md` P5.5 (approved 2026-10-24). First item: one core for voice and chat
(`v4-notes/p5.5-core-merge.md`). Then the inventory below, the refactors (one concern per commit, both languages),
the measures before and after, and an independent design review.

## Measures

How: `v4-notes/tools/measure.py` on a tree exported from a commit (`git archive <commit> python node`), run with a
scratch venv holding `lizard` (function length, cyclomatic) and `complexipy` (Python cognitive complexity) and a scratch
`eslint@8.57.0` + `eslint-plugin-sonarjs@0.25.1` (Node cognitive complexity). Scope: `python/crowkis/{turns, rules,
runtime, understanding, state, keys, channels, integrations}` and the package's top-level modules (not `client.py`,
`grpc_stub.py`), and everything in `node/src/`. Detail per function: `v4-notes/tools/measure-<label>.json`.

| Measure | Python before (`9b04b92`) | Python after | Node before (`9b04b92`) | Node after |
|---|---|---|---|---|
| Files | 140 | | 116 | |
| Functions | 707 | | 907 | |
| Cognitive complexity, highest | 80 (`call_context._states_self`) | | 70 (`callContext.js`) | |
| Cognitive complexity, mean of functions with any | 3.07 | | 4.31 | |
| Functions over 15 cognitive | 25 | | 18 | |
| Function length, longest (NLOC) | 106 | | 110 | |
| Function length, mean (NLOC) | 7.17 | | 4.78 | |
| Functions over 20 lines | 43 | | 26 | |
| Cyclomatic, highest | 54 | | 49 | |
| File length, longest | 1257 (`channels/voice_session.py`) | | 1257 (`channels/voiceSession.js`) | |
| Files over 300 lines | 8 | | 4 | |
| Forward-only classes (80%+ of methods hand the call on) | 2 (`SessionCall`, `SessionHost`) | | (same twins) | |

Files one typical change touches (counted by hand, both languages together; before / after):

| Change | Before | After |
|---|---|---|
| Add a question rule | 6 (+1 fixture): the rule, `rules/question/__init__.py`, `rule_set.py`, and the three Node twins; `fixtures/rules/question/<Rule>.json` | |
| Change a threshold (the confidence floor) | 5: `frame_reading.py` and `rule_checker.py` (two separate 0.6s), their Node twins, `index.d.ts` ("Default 0.6") | |
| Add a counter | 7 (voice): `runtime/stats.py`, `channels/voice_session.py` (field, reset, `stats()`), the rule that counts; Node `stats.js`, `voiceSession.js`, the rule, `index.d.ts`. A Chat counter is a different set (`call_session.py` `counts` dict, string keys) | |
| Change a key part (the knowledge segment) | 4: `keys/knowledge_segment.py` (voice) and `RuleChecker.build_segment` (chat) build the same `kb=` / `channel=` fields, and their Node twins; 9 when the part needs a new setting (+ both facades' factories, `chat.py` / `chat.js`, `index.d.ts`) | |
| Fix a misfire (a word list) | 2 (+1 fixture): the theme module in `word_rules/` and its `wordRules/` twin (the lists are code in both languages, not shared data); a case in `fixtures/voice-rule-phrases.json` | |

## Inventory

Each file: clean, or not clean with the reason, and the commit that made it clean.

Read at `ff17478` (2026-10-24), after the core merge; per-function numbers from `measure.py` at that commit (cognitive
over 15, NLOC over 20). One line per file; a Python file and its Node twin share the line and the verdict (Node paths
under `node/src/`, camelCase). Python totals (the Node twins follow them): **46 clean, 101 not clean** of 147 files.
"Private imports" means names with a leading `_` taken from another package (Node: the same internals, unprefixed,
exported wholesale by `wordRules/index.js`).

### `turns/` (7 clean, 23 not clean)

- Clean: `__init__.py`; `answered` / `answered.js`; `chat_turn` / `chatTurn.js`; `hit` / `hit.js` (but typed late, see
  `cache_lookup`); `routes` / `routes.js` (public names); `voice_pairing` / `voicePairing.js`; `voice_reader` / `voiceReader.js`.
- `turn_core` / `turnCore.js`: not clean: (the write's `except` moved into `BoundedWriter`: `6673dca`) `Any` in every signature (`decide -> Any`, `record(answered: Any)`); the lookup lambda
  calls `settings.agent.ask` and gets a raw dict. Node: `isThenable` exported by the core, imported by `chatReader.js`.
- `turn_steps` / `turnSteps.js`: not clean: 15 `Any` (no step's subject or result is typed); `Report` has 6 methods
  and `VoiceReport` is also the `EarlyAnswers` (interfaces too wide).
- `verdict` / `verdict.js`: not clean: carries rule+reason+counts *and* outcome+route+answer: more than one job;
  `counts: Union[Counter, str]` (two counter systems).
- `decision` / `decision.js`: not clean: (`_Outcome` gone: `9a20210`, now `turns/outcome.RecordedOutcome`) `_audio_shareable`, `_session`, `_said` set from `VoiceReport`; actions as bare strings.
- `checked` / `checked.js`: not clean: `subject: Any`; `LookedUp.hit` is the raw dict (typed `Hit` wanted).
- `cached_answer` / `cachedAnswer.js`: not clean: private import `_fill`; `turn: Any`.
- `channel` / `channel.js`: not clean: Speculative Generality: `isolates_context`, `audio`, `saves_answers` read by nothing.
- `voice_call` (Node: typedef only): not clean: a 22-member interface (Interface Segregation; the host-interface concern).
- `session_call` / `sessionCall.js`: not clean: Inappropriate Intimacy (`session._tainted`, `session._heard_texts`);
  8 members only forward to `CallReadings` (Middle Man); `agent_key`'s getattr chain repeats `question_records.tenant_of`
  (Message Chain); `engine_vouches` runs a deadline inline (belongs in runtime).
- `voice_turn` / `voiceTurn.js`: not clean: private import `_CONTEXT_BOUND_THRESHOLD`; `reading: Any`; `getattr(reading, "frame")`.
- `model_answer` / `modelAnswer.js`: not clean: private import `_is_non_answer`.
- `voice_report` / `voiceReport.js`: not clean: three jobs (Report, EarlyAnswers, `model_messages`' privacy checks
  inline); writes the decision's private fields; private imports `_asks`, `_lookup_only`, `_unfinished` (`_Outcome`: gone, `9a20210`).
- `voice_saving` / `voiceSaving.js`: not clean: `_learn_personal` holds a privacy rule inline (the "undeclared" check,
  7 word-rule privates) that belongs to a save rule; 11 private imports; `agent: Any`. (Done: `cacheable` the same in
  both languages, `88a6480`; `_learn_personal` returns a `WriteResult` or None, no `Union` / `isinstance`, `9a20210`.)
- `chat_answers` / `chatAnswers.js`: not clean: (the app hooks' `except`s moved into `AppHooks`: `39549dd`) counts by
  magic strings (`"sharing_off"`, `"tools_answered"`); private imports `_masked`, `_norm`.
- `chat_reader` / `chatReader.js`: not clean: 6 private imports. (Done, `12fc34d`: the understanding boundary moved
  into `ChatUnderstanding`; Node's `within` copy gone, it uses `runtime/deadline.js`.)
- `chat_question_check` / `chatQuestionCheck.js`: not clean: translates between two `Verdict` types; `checker` /
  `replay: Any`; `counts[verdict.route]` by string; private import `_private_words`.
- `chat_hit_check` / `chatHitCheck.js`: not clean: reads the raw hit dict (`hit.get("route")`) before typing it; `turn: Any`.
- `chat_reading` / `chatReading.js`: clean (`88a6480`: `segment` sent only when set, in both languages).
- `chat_report` / `chatReport.js`: not clean: counts by string keys; `SAVE_REFUSED` defined again in `chat_saving`;
  `reading: Any`. (Outcomes from `Outcome`: `9a20210`.)
- `chat_saving` / `chatSaving.js`: not clean: `verdict: Any`; private import `_masked`. (Outcomes from `Outcome`, a
  typed `WriteResult`: `9a20210`; a refused write reported through `ChatReport`: `6673dca`.)
- `chat_turns` / `chatTurns.js`: not clean: public mutable `next_turn`. (Outcome words from `Outcome`: `9a20210`.)
- `chat_answer` / `chatAnswer.js`: not clean: `verdict: Any`; a second save subject beside `ModelAnswer` (paired save rules).
- `turn_result` / `turnResult.js`: not clean: `verdict: Optional[Verdict]` names a class it never imports (undefined name).

- New in the refactors, clean: `outcome` / `outcome.js` (`Outcome`, `RecordedOutcome`: a `str`, as callers compare it
  with the word; Node's outcome stays the `{ outcome, why, rule }` object), `app_hooks` / `appHooks.js`,
  `chat_understanding` / `chatUnderstanding.js` (`turns/`, beside `ChatReader`, so Node's `isThenable` import does not
  point from `understanding/` to `turns/`); `runtime/write_result` / `writeResult.js`, `runtime/deadline.py` (Python
  twin of `deadline.js`).

### `rules/` (2 clean, 4 not clean) and its stage folders

- Clean: `__init__.py`; `chat_rule_set` / `chatRuleSet.js`.
- `rule` (Node: d.ts only): not clean: the stage interfaces type voice subjects only (`check(turn: VoiceTurn)`); the
  chat rules take `ChatTurn` / `ChatAnswer`, so the interface does not describe half its implementations.
- `chain` / `chain.js`: not clean (minor): `subject: Any`; `_holds_floor` reads another chain's `_rules`; Node
  requires `../../index.js` for `CrowkisError` (the index cycle, below).
- `rule_set` / `ruleSet.js`: not clean: seven chains plus a lone `personal` rule with its own `check()` / `refusal()`
  API, not three stages (review-later 2.7); `hit: Dict[str, Any]`.
- `rule_checker` / `ruleChecker.js`: not clean: two jobs (V1-V10, and key / segment building, which belongs in
  `keys/`); a second, mutable `Verdict` (clashes with `turns.Verdict`); re-exports 16 private `frame_words` names;
  rebuilds its rules when `confidence_floor` changes; literal kinds (`"personal"`, `"live"`); the 0.6 floor again.
- `question/` (11 clean, 14 not clean). Uniform: one class, `name` / `floor` / `check`, one `Verdict`. Clean:
  `__init__`, `about_someone`, `empty_turn`, `follow_up_without_context`, `no_question`, `not_general`, `own_records`,
  `task_step`, `too_short`, `uncertain_frame`, `urgent_turn`. Not clean, private `word_rules` / `frame_words` imports:
  `call_context_taint`, `cut_off`, `identifying_details`, `lost_detail`, `private_chain`, `question_names_caller`,
  `registered_filler`, `told_detail_dropped`, `ungrounded`, `unresolved_reference`, `urgent_words`,
  `voice_stated_facts`; also `stated_facts` (Long Method `_drops_a_listed_item`, cognitive 19; twin of
  `voice_stated_facts`) and `untagged_name` (`check`, cognitive 18). Chat rules count by strings, voice rules by `Counter`.
- `hit/` (6 clean, 3 not clean). Clean: `__init__`, `commitment_rewording`, `confidence_bar`, `different_question`,
  `short_turn_unvouched`, `template_slot_missing`. Not clean: `pii_placeholder`, `screen_only_answer` (private
  imports); `commitment_policy` (the same table again as `word_rules/phrases._COMMITMENTS`, there on a dict).
- `save/` (5 clean, 17 not clean). Clean: `__init__`, `attribute_not_in_key`, `no_key`, `not_shareable`,
  `tainted_call`. Not clean: seven voice / chat twins that differ only in reason wording and counters (`empty_answer` /
  `chat_empty_answer`, `non_answer` / `chat_non_answer`, `tool_result` / `chat_tool_result`, `caller_identifier` /
  `chat_caller_identifier`, `prompt_caller_details` / `chat_prompt_details`, `private_word` / `voice_private_word`,
  `action_claim` / `voice_action_claim`); `declared_value`, `identifying_answer`, `personal_template` (private imports;
  `personal_template` also has the extra `refusal()` API). (Outcome words copied per file: gone, `Outcome`, `9a20210`.)

### `runtime/` (2 clean, 5 not clean)

- Clean: `__init__.py`; `write_workers` (Python only); Node-only `deadline.js`.
- `bounded_writer` / `boundedWriter.js`: not clean: imports `turns.Verdict` / `Outcome` (runtime -> turns -> runtime).
  (Done: `write_within` returns a typed `WriteResult`, `9a20210`; the write's one error boundary, `6673dca`. `write()`
  keeps its `Optional[Verdict]`, the bounded wait inside the boundary.)
- `cache_lookup` / `cacheLookup.js`: not clean: returns `Tuple[raw dict, Verdict]` (typed `Hit` wanted); "voice budget" wording for chat too.
- `question_records` / `questionRecords.js`: not clean: reads `agent._client` and sends raw `get` / `set` (server
  independence: `transport/`, P5.7); private imports `_QUESTION_KEY`, `_different_specifics`.
- `stats` / `stats.js`: not clean: voice only; Chat counts in a string-keyed dict: two counting systems.
- `turn_pairing` / `turnPairing.js`: not clean: public mutable `open` / `cancelled` / `mark` / `turn`; `Tuple[int, bool]`.

### `understanding/` (6 clean, 12 not clean) and `word_rules/` (0 clean, 11 not clean)

- Clean: `__init__`, `llm_classifier`, `llm_rewriter`, `replay_rewriter` (+ twins), `slots`, `text_only_classifier` (Python only).
- `budgeted_understanding` / `.js`: not clean: a full in-flight limit is raised as `TimeoutError`, counted as `understand_timeouts`.
- `understanders` / `.js`: not clean: `WithFallback` catches `Exception` (a third understanding boundary); a third
  `_normalise`; Chat's `Understander` and voice's `Classifier` / `Rewriter` are two understanding interfaces.
- `rewrite_check` / `.js`: not clean: five private imports; its own crude stemmer (`rstrip("s")`); `rewritten: object` + `isinstance`.
- `frame_words` / `.js`: not clean: stemmer #1 of three; a second `_EMAIL` / `_LONG_DIGITS` (other patterns); its
  underscored names are the API of 8 rule files.
- `answer_patterns` / `.js`: not clean: a third `_EMAIL` and a second `_LONG_DIGITS`, each a different pattern.
- `chat_details` / `.js`: not clean: Long Method `_names` (cognitive 35, Node 32); imports `_FUNCTION` from
  `rules.rule_checker` (understanding -> rules: the wrong direction); its private functions serve four `turns/` files.
- `call_readings`, `fact_relevance`, `word_rule_classifier` (+ twins): not clean: private imports from `word_rules`,
  `chat_details`, `frame_words`.
- `frame_reading` / `.js`: not clean: `CONFIDENCE_FLOOR = 0.6`, repeated as `RuleChecker`'s literal default.
- `turn_frame` / `.js`: not clean: Long Method `from_dict` (35 lines; Node cognitive 24). Its `Any` is fine (validation boundary).
- `no_rewrite` / `.js`: not clean (minor): `reading: Any` where `Reading` exists.
- `word_rules/__init__` / `index.js`: not clean: the package's whole API is ~250 private names (Node: every internal exported).
- Long Method: `call_context` (`_states_self`, cognitive 80 / Node 70), `personal` (769 lines; `_never_share` 60,
  `_identifies` 48, `_names_someone` 47; a fourth `_EMAIL`), `prompt_details` (`_prompt_details` 53), `text` (598
  lines; `_capitalised_name` 28; stemmer #2; a `_normalise`), `identifiers` (`_identifiers` 24), `answers`
  (`_is_non_answer` 21), `urgent` (`_urgent` 18), `follow_up` (`_has_bare_anaphor` 17); twins alike.
- `high_risk`: not clean: its own `_NUMBER_WORDS`, a different list under `text.py`'s name. `phrases`: not clean:
  `_COMMITMENTS` duplicates `COMMITMENT_POLICIES`; `_CONTEXT_BOUND_THRESHOLD` is a lookup setting, not a phrase.

### `state/` and `keys/` (2 clean, 2 not clean)

- Clean: `state/__init__.py`, `keys/__init__.py`.
- `call_state` / `callState.js`: not clean: `apply` cognitive 16 (Node 18), `from_dict` 25 lines; fields set from outside (`state.language` in `ChatReader`).
- `knowledge_segment` / `knowledgeSegment.js`: not clean: Chat builds the same fields in `RuleChecker.build_segment` (Shotgun Surgery).

### `channels/` (1 clean, 5 not clean)

- Clean: `__init__.py`.
- `voice_session` / `voiceSession.js`: not clean: 1108 lines, Large Class (settings, composition root, audio, stats
  reporting, `warm_from_calls`, `VoiceResponse` with `_run` cognitive 29 / Node 31, `__init__` 104 lines); ~240 lines
  re-exporting private word-rule names; `agent._client.cvoicestat` (private attribute, raw command); `getattr(self, "_text_only")`.
- `async_voice_session` (Python only): not clean: `AsyncVoiceResponse._run` 72 lines, cognitive 35.
- `call_session` / `callSession.js`: not clean (`emit` no longer catches: `AppHooks`, `39549dd`): re-exports 15 private names (`noqa: F401`); `__init__` 44 lines;
  `_lookup` builds a stand-in `ChatReading` to reach the core.
- `chat` / `chat.js`: not clean: imports `_masked` through `call_session`; `turn` cognitive 16 (Node 17).
- `realtime` / `realtime.js`: not clean: bare `except Exception:` around `decide`, no count or log (outside a boundary); `getattr` duck typing.

### `integrations/` (2 clean, 4 not clean)

- Clean: `__init__.py`; `memory` (a public adapter that forwards by design).
- `voice_turns` / `voiceTurns.js`: not clean: imports `_store_later` / `_tts_key` from `agent` and `_words` through
  the voice facade; three `except Exception` (audio and read boundaries mixed).
- `pipecat` (Python only): not clean: `_answer` 52 lines (cognitive 22), `process_frame` cognitive 21; re-exports private names.
- `livekit` (Node twin `node/livekit.js`, outside `src/`): not clean: `llm_node` 81 lines, cognitive 42; `except BaseException`. (`Any` here is the framework boundary: allowed.)
- `langchain`: not clean (minor): two broad `except Exception` used as format fallbacks: narrow them.

### Top level (2 clean, 1 not clean) and Node's entry

- Clean: `__init__.py` (note: the public `Verdict` is `RuleChecker`'s); `privacy` / `privacy.js` (the stable public names).
- `agent` / `node/agent.js`: not clean: a module-level audio worker thread and queue (global mutable state); `speak`
  65 lines, cognitive 35; `ask` 52 lines; `_store_later` / `_tts_key` used by three other packages.
- `node/index.js` re-exports: not clean: `src/` requires `../../index.js` (`CrowkisError`, `CrowkisClient`) while
  `index.js` requires `src/`: a cycle the lazy getters work around (ends with P5.7's client split).

## Refactor plan

One concern per commit, Python and Node together, golden identical unless a line says otherwise. In order of value.

1. **Done (`88a6480`). Python / Node parity.** *Voice `cacheable`*: Python's is right (`shareable and not private`): a tool-built answer
   is never shared even when an app turns `ToolResult` off with `without()`. Node takes only what decide() offered, so
   with `ToolResult` off it would share a tool-built answer today. Aligning Node changes nothing while `ToolResult` is on
   (golden unchanged); with it off, Node now keeps the answer: a privacy fix, failing-first Node test. *Chat `segment`*:
   Node's is right (sent only when set). `Agent.ask` drops a falsy segment in both languages, so the server sees the
   same command; only a fake agent's keyword arguments differ. Files: `voiceSaving.js`, `chat_reading.py` (+ tests).
2. **Done (`9a20210`). `Outcome` enum and a typed `WriteResult`.** `Outcome(str, Enum)` with today's words (equality and JSON
   unchanged) replaces `_Outcome` (kept as an alias where re-exported) and the save rules' `KEPT` / `PRIVATE` copies;
   Chat's `"refused:<why>"` is built from it. `BoundedWriter.write_within` returns `WriteResult` (written, slow_write,
   not_written, refused); `_learn_personal` returns one too: no `Union`, no `isinstance`. Files: `turns/{decision,
   verdict, voice_report, voice_saving, voice_pairing, chat_report, chat_saving, chat_turns}`, `runtime/bounded_writer`,
   `rules/save/*` (11), `channels/voice_session`; twins.
3. **Partly done (`6673dca` the write, `39549dd` `AppHooks`, `12fc34d` `ChatUnderstanding`). Error boundaries only in
   their boundary classes.** The write's catch leaves `TurnCore` for `BoundedWriter`;
   `ChatReader` uses `BudgetedUnderstanding` (Node: `runtime/deadline.within`), not its own copy; one `AppHooks`
   boundary for `on_urgent` / `on_tools` / `on_event`; `realtime` counts and logs its fallback; `engine_vouches`'
   deadline moves to runtime; one audio boundary. Files: `turn_core`, `bounded_writer`, `chat_reader`, `chat_answers`,
   `call_session`, `realtime`, `session_call`, `understanders`, `voice_turns`, `voice_session`; twins.
   *Left:* `realtime`'s fallback count and log, `engine_vouches`' deadline, one audio boundary, `WithFallback`'s catch.
   *Not as planned:* Chat's understanding could not use `BudgetedUnderstanding` without a behaviour change (it would add
   a warning log per fallback, the 4-call in-flight limit, the word-rule fallback and `Counter` counts instead of the
   replay fallback and `counts`); it got its own boundary, `ChatUnderstanding`, on `runtime/deadline`. Merging the two
   needs the owner's go (and the one understanding interface, review-later 3).
4. **`Verdict` doing one job.** `Verdict(rule, reason, counts)`; a save rule's outcome comes from the stage (an
   `Outcome` per rule), a rule that answers or routes returns an `EarlyAnswer(route, answer)` (`RegisteredFiller`,
   `UrgentTurn`, `TaskStep`, `UrgentWords`); `RuleChecker`'s verdict becomes an immutable `ChatVerdict` inside (public
   `Verdict` stays an alias), so `ChatQuestionCheck` stops translating. Files: `turns/{verdict, voice_report,
   chat_answers, chat_question_check, chat_reading, turn_result}`, `rules/rule_checker`, those four question rules,
   `rules/save/*`, `__init__` / `index.js`; twins.
5. **Host / session interfaces narrowed.** `VoiceCall` (22 members) split into the views each stage reads (settings,
   what the call heard, its context); `SessionCall` owns `tainted` and the heard turns instead of the facade's
   privates; rules read `CallReadings` directly (the 8 forwards go); the six chat session `Protocol`s become injected
   state, counters and settings; `VoiceReport` loses `EarlyAnswers` and `model_messages`. Files: `voice_call`,
   `session_call`, `voice_report`, `voice_saving`, `call_readings`, `chat_{answers, reader, question_check, hit_check,
   report, saving}`, `voice_session`, `call_session`; twins.
6. **No `Any` outside framework boundaries.** Type variables in `turn_steps`, typed `Checked` / `LookedUp`;
   `CacheLookup` returns a `Hit` (typed at the lookup, not in the hit checks); an agent `Protocol` for `agent: Any`;
   `ChatAnswer.verdict` and `TurnResult.verdict` typed (fixes the undefined name). Files: `turn_steps`, `turn_core`,
   `checked`, `cache_lookup`, `chat_hit_check`, `rule_set`, `cached_answer`, `voice_turn`, `chat_*`, `turn_result`,
   `no_rewrite`, `chain`; twins (JSDoc, d.ts).
7. **No private names across packages.** `word_rules`, `frame_words`, `chat_details`, `answer_patterns` each get a
   small public interface (the ~40 names other packages use); `chat_details` stops importing from `rules`;
   `_store_later` / `_tts_key` become a runtime audio-store piece; the ~255 names the facades re-export for old paths
   move to one legacy module per facade (old imports keep working). Node: `wordRules/index.js` exports that interface
   only. Files: `understanding/*`, the not-clean rule files, `turns/*`, `question_records`, `channels/*`,
   `voice_turns`, `pipecat`, `agent`; twins.
8. **One stemmer, one copy of each pattern.** Three stemmers (`frame_words`, `word_rules/text`, `RewriteCheck`), four
   `_EMAIL`, two `_LONG_DIGITS`, two `_NUMBER_WORDS`, three `_normalise`. Caution: the stemmers disagree ("news",
   "bus", "prices"), and `frame_words._stem` feeds Chat's `told=` segment hash (another stem = another key = lost
   entries). Keep `frame_words`' stemmer; switch each other caller only where golden and the phrase fixtures show no
   decision changes, else it is a behaviour change for the owner. Files: those modules, `personal`, `high_risk`,
   `understanders`, `chat_details`; twins.
9. **P4 rough edges (review-later 5).** `RewriteCheck.accept(rewritten: Optional[str])`, validated once in
   `BudgetedUnderstanding`; a full in-flight limit gets its own outcome and counter (a new `stats()` key: an addition
   for the owner to confirm). Done already: the facades build `RewriteCheck` (composition roots). Private imports and
   the stemmer: commits 7, 8; `VoiceCall` growth: 5. Files: `rewrite_check`, `budgeted_understanding`, `voice_reader`,
   `stats`, `voice_session`; twins, d.ts.
10. **One counting system.** Chat's string-keyed `counts` becomes `Stats` with `Counter` members (the public dict stays
    a view); rules name `Counter`s only. Add a counter: 7 -> 4. Files: `stats`, `call_session`, `chat_*`, the chat rules; twins, d.ts.
11. **One place per key part and threshold.** Key and segment building leave `RuleChecker` for `keys/`
    (`KnowledgeSegment` builds `kb=` / `channel=` for both channels); `RuleChecker`'s default floor reads
    `CONFIDENCE_FLOOR`; `_CONTEXT_BOUND_THRESHOLD` moves to the lookup settings. Key part 4 -> 2, floor 5 -> 3.
    Files: `knowledge_segment`, `rule_checker`, `frame_reading`, `phrases`, `voice_turn`; twins.
12. **Merge the voice / chat pairs that differ by a setting (review-later 6).** The seven save-rule twins (wording and
    counters from the channel profile), `stated_facts` / `voice_stated_facts`; `RuleSet` as three stages (the lone
    `personal` rule joins a chain; `_learn_personal`'s check becomes a save rule). Files: `rules/save/*`, those two
    question rules, `rule_set`, `chat_rule_set`, `rule`, `voice_saving`, `chat_answer`, `model_answer`; twins.
13. **Long Methods.** The word rules (`_states_self` 80 down to `_has_bare_anaphor` 17), `chat_details._names`,
    `TurnFrame.from_dict`, `CallState.apply` / `from_dict`, `RuleChecker._key_attributes`, `stated_facts`,
    `untagged_name`: named steps, phrases as named data, proven by the phrase fixtures and golden. Twins alike.
14. **Large classes.** `VoiceSession` split (`VoiceResponse`, audio, stats reporting, `warm_from_calls` in their own
    files; public API unchanged), `AsyncVoiceResponse._run`, LiveKit `llm_node`, Pipecat `_answer` / `process_frame`,
    `Agent.speak` / `ask`; the module-level audio worker becomes an injected runtime object. Twins (`node/livekit.js`, `node/agent.js`).
15. **Leftovers.** `Channel`'s unused fields; `phrases._COMMITMENTS` vs `COMMITMENT_POLICIES`; `TurnPairing`'s public
    flags behind methods; Node `isThenable` out of `turnCore.js`; narrow catches in `langchain`. The `index.js` cycle ends in P5.7.
