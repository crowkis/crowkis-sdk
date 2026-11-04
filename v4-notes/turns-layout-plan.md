# Plan: `turns/` in the fewest files, grouped in meaningful subfolders (2026-11-04)

The owner wants the fewest files, each in a subfolder that means something. This plan builds on
`turns-ultra-audit.md`: its deletions run first, then the files are regrouped. Nothing changes behaviour: golden
files stay identical and public names stay the same. Python and Node change together.

## Target layout

```
turns/                          what every channel shares
  __init__.py                   docstring only (Python needs the file; no re-exports)
  core.py        TurnCore + the step interfaces (turn_core, turn_steps)                      ~170
  values.py      Verdict, Checked, LookedUp, Outcome, RecordedOutcome, Hit, CachedAnswer,
                 Channel (verdict, checked, outcome, hit, cached_answer, channel)             ~185
  results.py     TurnDecision, TurnResult, the route constants, VoiceAnswered, ChatAnswered
                 (decision, turn_result, routes, answered): what a session hands out and takes back  ~130
  voice/
    __init__.py  empty
    call.py      SessionCall (session_call)                                                   ~160
    turn.py      VoiceTurn, ModelAnswer, VoiceReader (voice_turn, model_answer, voice_reader):
                 a voice turn as read, and what voice's rules read                            ~145
    steps.py     VoiceReport, VoiceSaving (voice_report, voice_saving)                        ~290
  chat/
    __init__.py  empty
    turn.py      ChatReading, ChatReader (+ ChatUnderstanding folded in), ChatTurn, ChatAnswer
                 (chat_reading, chat_reader, chat_understanding, chat_turn, chat_answer)       ~180
    checks.py    ChatQuestionCheck, ChatHitCheck (+ ChatHitCall, ChatHitTurn)                  ~130
    steps.py     ChatTurns, ChatAnswers (+ the app-hook function), ChatReport, ChatSaving
                 (chat_turns, chat_answers, app_hooks, chat_report, chat_saving)               ~300
```

Gone: `voice_call.py` (a Protocol with one implementation) and `voice_pairing.py` (folded into
`runtime/turn_pairing.py`).

The voice and chat folders mirror each other. `turn` is a turn as read plus what the rules read. `steps` holds the
core's report, saving and pairing slots. Chat also has `checks`, because voice's question and hit checks live in
`rules/rule_set.py`.

| | Files now → after | Lines now → after (approx.) |
|---|---|---|
| Python `turns/` | 33 → 12 (incl. 3 `__init__.py`) | 2,035 → ~1,690 |
| Node `turns/` | 31 → 9 | 1,813 → ~1,700 |

## Steps (each one commit; full Python + Node suites after each; golden files unchanged)

1. **Deletions from the audit.** Audit #1 and #2: `VoiceCall` and the ten one-implementation session Protocols
   (Python only). #7: `Report.refused` comes out of the core's interface. #13: `_outcome` goes. #16: the duplicate
   `SAVE_REFUSED` goes. #14: `keyed()` goes. #15: `VoiceReader`'s `rewrite_check` parameter goes. Risk: none or
   low.
2. **Folds that remove a class.** #5: `ChatUnderstanding` goes into `ChatReader`. #3: `AppHooks` becomes one
   function (Node: a test that checks the async step order). #4: `VoicePairing` goes into `TurnPairing`, whose
   `settle` is renamed `settle_turn`, with tests.
3. **The move.** Each new file is made with `git mv` from its biggest source file, so history follows, and the rest
   is appended. Every import is repointed. `turns/__init__.py` becomes a docstring. Python callers
   (counted in T1):
   - `rules/`: about 12 files import from `..turns` or `turns.*`.
   - `channels/voice_session.py` and `channels/call_session.py`.
   - `runtime/bounded_writer.py`, `runtime/cache_lookup.py`, `runtime/write_result.py`.
   - `understanding/rewrite_check.py`.
   - The root `__init__.py`: `Channel` now comes from `turns.values`, the routes from `turns.results`.
   - The tests under `tests/turns/`, `tests/rules/` and 5 root tests.

   Node: the same files in `node/src`, plus `index.js:1354` (the routes spread) and `index.js:1418-1428` (the
   `Channel` getters). The `.d.ts` files name no `turns/` path. Cycle check: `understanding/rewrite_check`, `slots`,
   `chat_details` and `state` import nothing from `rules/` or `turns/` except `rewrite_check`'s TYPE_CHECKING-only
   `VoiceCall` import, which step 1 removes. So `voice/turn.py` can hold the reader.
4. **Check.** Run the full suites twice, the frameworks (Pipecat, LiveKit Py/JS, Bolna) once, and
   `graphify update .`. Then an Opus review of the move commit: is it a pure move, did any import cycle appear,
   are public names unchanged.

## Choices for the owner

- **Chat's checks go into `rules/` instead?** `ChatQuestionCheck` and `ChatHitCheck` are chat's twin of
  `rules/rule_set.py`. Moving them to `rules/chat_rule_set.py` would leave `chat/` with 2 files, but it changes a
  folder outside `turns/`. Not in this plan.
- **No subfolders?** Flat `voice_call`, `voice_turn`, `voice_steps`, `chat_turn`, `chat_checks`, `chat_steps` is
  10 Python files instead of 12, because subfolders need an `__init__.py` each. Node is 9 files either way.
