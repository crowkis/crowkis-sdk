# P1 review (Opus): fixes and tests, `9a663c5^..HEAD` plus the two untracked cross-channel tests

Read only. Probes ran against HEAD and against a `git archive 9a663c5^` copy (baseline) in the scratchpad, voice through
`voice_session(client=ConformanceStore())` and Chat through the `test_stated_name._chat` helper. All voice probes (88
cases) produce identical shared writes in Python and Node.

## Summary

- **Must-fix: 4.** Common Indian-English ways of giving a name are still not captured, so the stated-name fix misses
  them (M1). Chat drops `identifiers` between turns, so `ChatCallerIdentifier` only ever sees the current turn and the
  "phone said in words" fix does nothing in Chat (M2). Two tests can't fail as written: the fuzz Devanagari-name case
  saves nothing even with no leak (M3), and the adapter failure-matrix still skips the log check on the row F2 fixed (M4).
- **The fixes leak no more than before.** VD8 (opener strip) and T11 (stranded preposition) make more turns shareable,
  but every probe that newly saves is a general question. A preamble holding a name or number is left as it was, and
  stays private. N1, the logging change and B4 are correct, and the logging is now complete.
- **Tests:** they are mostly real. The privacy fuzz "stated earlier" cases are not vacuous (I counted controls: 45/60,
  12/12, 30/30, 46/60 and 30/30 save when the answer has no detail), but the test never asserts that, and its
  generators are shaped to the rules the fix implements.

---

## 1. The fixes

### M1 (must-fix, privacy). Name phrasings the stated-name capture misses: the answer is saved shared
`_stated_names` (python/crowkis/understanding/word_rules/personal.py:836-866, node .../personal.js:750-784) only reads
names after `my name is / name's / call me / mera naam / naam / I'm / I am / this is`. Voice repro: turn 1 is the
intro, turn 2 is `what is the refund policy` answered with "Refunds in 7 days, Rahul.". The answer **is saved shared**
(Python and Node) after:

| intro | voice | Chat (personal frame, no entities) |
|---|---|---|
| `Rahul here` / `rahul here` | leaks | leaks |
| `Rahul this side` / `hello, Rahul this side` | leaks | leaks |
| `myself Rahul`, `myself rahul verma` | leaks | caught (by `_private_words`) |
| `it's Rahul`, `its rahul`, `it is Rahul` | leaks | caught |
| `Rahul speaking` | leaks | - |
| `you're speaking with Rahul` | leaks | - |
| `mera naam hai Rahul` | leaks | - |
| `my good name is Rahul`, `the name is Rahul`, `my first name is Rahul` | leaks | - |
| `Rahul.` (bare answer to "may I have your name") | leaks | - |

Partial captures, caused by `_NAME_PARTS = 2` and the glued suffix:
- `my name is Priya Iyer Sharma` + an answer with "Ms Sharma": leaks in voice. `my name is Dr. Rahul Verma`
  catches "dr" and "rahul", so an answer with "Mr. Verma" would leak.
- `my name is Rahul Verma` + "Refunds in 7 days, **Rahulji**.": leaks in voice and Chat (Hindi honorific glued on).
- `my name is mary-jane smith`: captures only mary and jane.

Fix direction: add leads `X here`, `X this side`, `X speaking`, `myself X`, `it's/it is X`, `speaking with X`,
`naam hai X`, `(good|first) name is X`, `the name is X`. Take names up to a stop word instead of exactly 2 words. Match
a stated name as a word prefix too (`rahulji`). Add these phrasings to `INTROS` in both tests.

### M2 (must-fix, privacy, pre-existing but it defeats the Chat half of 08a24f7). Chat loses `identifiers` every turn
`CallState.to_dict` (python/crowkis/state/call_state.py:252-270) does not write `identifiers` (on purpose, see the
comment at :77-80), while `from_dict` (:297) reads it. `Chat.turn` restores state from the store every turn
(channels/chat.py:108-125), so `ChatCallerIdentifier` (rules/save/caller_specific.py:34-46, "said anywhere in this
chat") only ever sees the current turn. Repro (Python `_chat` helper; personal frame without entities, as a model that
misses the entity returns):
- `my number is nine eight double four five`, then "Call nine eight double four five." is **saved**.
- `my number is 98450 67881`, then "We will call nine eight four five zero six seven eight eight one." is **saved**.
- Patching `to_dict` to include `identifiers`: both are refused.

Digit IDs are caught today only because `_private_words` captures digit tokens and `IdentifyingAnswer` catches long
digit runs in the answer. Spoken digits are caught by neither. Node: same structure (check `toDict` in
node/src/state/callState.js). Fix: keep the identifiers in memory per thread (they must not be exported, so not in
`to_dict`), or note them as private words (hashes) from `_spoken_numbers` runs. The test (`test_stated_name.py`
`test_a_phone_said_in_words_is_not_shared`) covers only voice. Add a Chat case.

### VD8: opener strip (db96224). No new leak found
- `_strip_preamble` (text.py:108-123 / text.js:120-135) strips only exact members of `_PREAMBLES`, so nothing private
  is removed. `_without_preamble` (follow_up.py:206-210) keeps the original when the rest is personal.
- Probes, all private or not shared, the same before and after: `Hi, Rahul here, what are your hours?`,
  `hey it's priya, what time do you close?`, `Hmm, my account 4821, what is the fee for?`,
  `Okay, rahul here, ...`, `Hi, I'm Rahul, ...`, `Hello, this is priya, ...`, `haan ji, mera naam Rahul hai, timings kya hai?`,
  `Okay, Rahul, what are your hours?`, `uh, Rahul, what time do you close?`, `Okay, okay, I'm Rahul, ...`,
  `Hi there, quick question, Rahul Verma here, ...`.
- Newly saved: `Hmm, what are your hours?` and `Hi, hello, hmm, okay, what are your hours?`, keyed as the bare question.
- Follow-ups after an opener key on the earlier turn correctly: `Okay, and for bags?` is keyed
  `...shoes? || and for bags?`.
- Note: Hinglish openers (`haan ji`, `accha`, `ji`, `arre`) are not in `_PREAMBLES`. That only costs hits.

### T11: stranded preposition (db96224). No new class of leak, but it widens a pre-existing one (note)
Newly shareable: `What is the charge for?`, `What is this charge for?`, `What is the payment for?`, `What is the hold on?`,
`Which account is the refund going to?`, `Who is the payment from?`, `What is the extra 500 for?`.
Their non-stranded twins were already shared at baseline (`What is this charge?`, `Who sent the payment?`,
`Where will the refund be credited?`), so T11 only brings the stranded forms to parity with them.

The underlying gap is pre-existing: a deictic or caller-specific question without "my" is shared. If the app gives the
model the whole call or tools, an answer like "To your HDFC account ending 4821" is saved, and no save rule catches a
value the caller never said. Worth an item in open-items, not a P1 blocker. `_STRANDED_MIN_WORDS = 4` keeps
`What is it for?` private (it is a follow-up). Good.

### VD4 (db96224). Correct and conservative
`can I pay it` / `again` / `as you said` now read as follow-ups. `can I pay it online?` alone is no longer shared
(follow-up with no earlier turn), and `What are your hours again?` keys on the previous turn (costs hits only).
Python and Node are identical.

### Spoken numbers (08a24f7)
- Works: runs of 4 or more digits, `double` / `triple`, `oh`, runs that cross punctuation, a caller's digits against an
  answer's words and the reverse (voice).
- Not covered, all notes (over-blocking or pre-existing limits):
  - Mixed digits and words (`98 four five 67 one two`): nothing is captured.
  - Hindi or Hinglish number words (`nau aath chaar paanch`, `ek do teen`).
  - Runs under 4 digits (consistent with digits).
  - An answer repeating only the last 4 of a 10-digit phone (`ending 7881`): long values need the full substring.
    Pre-existing for digits.

### N1 (655d906). Correct
`_readWithin(this.timeoutMs)` (node/src/client/commands.js:196) bounds the AUTH reply. On timeout it closes the
socket, and the retry and `_closing` handling are fine. Note: a hung handshake can now take connect timeout plus read
timeout (about 2x `timeoutMs`). The stale comment at node/test-failure-matrix.js:263-264 still says "the client has no
timeout on the AUTH reply".

### Logging (beb8647). Complete
Grep of every `_LOG / _log / logging / warnings / console.* / emitWarning` under python/crowkis and node/src:
- Every exception-bearing log now names the type only.
- Remaining non-type texts are the server's fixed `NOTSTORED` reasons (commands.py:371, commands.js:86) and Python's
  understanding fallback (slots.py:194, which is built from a type name or the budget). Both are fine.
- `decision.not_stored` / `decision.reason` still carry `str(error)` (steps.py:105, steps.js:95). That is returned to
  the app, not logged. Note: an adapter that logs `reason` would re-expose it.
- Parity note: Python logs refused writes and failed requests; Node logs neither (pre-existing).

### Constants, duplication (should-fix)
- `len(value) >= 2` in `_stated_names` / `statedNames` is an unnamed threshold (personal.py:866, personal.js:782).
- `_NAME_LEADS` duplicates the existing `_NAMING` (personal.py:873, personal.js:788). There are now two lists of
  name-giving phrases, and M1 needs to extend both. Keep one.
- Over-capture to know about (costs hits only): with the strong leads, `call me tomorrow` / `call me later` makes
  "tomorrow" / "later" a *name*. In Chat these go into `note_names`, so a later shared question containing "tomorrow"
  is refused by `QuestionNamesCaller`.

---

## 2. The tests

### M3 (must-fix, the test cannot fail). Fuzz `v-dev-name` (Devanagari name stated earlier)
test_privacy_fuzz.py:318-324 and test-privacy-fuzz.js:314-319 have no count assertion. With the answer stripped of
the name, **0 of 10** calls save anything: the Devanagari intro makes the whole call private (`caller told it
something`). So the leak search runs over an empty write list and can never fail. `v-hi-name` saves in only 5 of 10
calls. Add a control that the same calls save without the name, and assert a minimum. Same for every "stated earlier"
case, see S1.

### M4 (must-fix). The adapter failure-matrix still skips the log check on the F2 row
test_failure_matrix_adapters.py:56 skips `no_caller_text_in_logs` for `cset_error_quotes_question` ("that row's log
leak is the core file's BUG F2"). F2 is fixed (beb8647), so the skip now hides any adapter that logs the server's
error text. Remove the exclusion.

### S1 (should-fix). The privacy fuzz "stated earlier" controls exist only by luck
I counted saves with the detail removed from the answer:

| case | saved without the detail | saved with it |
|---|---|---|
| v-earlier | 45/60 | 0 |
| v-words | 12/12 | 0 |
| v-name | 30/30 | 0 |
| c-earlier | 46/60 | 0 |
| c-name | 30/30 | 0 |

So these cases do exercise the save path today. Nothing asserts it, though: a change that taints every call after any
detail would turn them vacuous silently. `MIN_CONTROL_SAVES` covers only single-turn general questions. Add the
paired control per category.

### S2 (should-fix). The fuzz generators are shaped to the implementation
- `SAY["name"]` uses only `my name is / this is ... calling / I am`, the exact leads `_stated_names` knows. None of the
  M1 phrasings are generated.
- The Chat fuzz always gives a perfect personal frame with entities (`as_chat` → `personal_frame`). The frame does the
  work, so the backstops (`ChatCallerIdentifier`, `_stated_names`, spoken numbers) are never tested. That is why M2 is
  invisible. Add a Chat variant whose frame has no entities.

### S3 (should-fix). The failure matrix's log checks are weaker than they read
- test_failure_matrix.py:194-195: `LOGS_A_MESSAGE` and its comment ("logged with a message, not the error type (BUG
  F1)") are stale. `check_voice_cell` still exempts those rows from the per-cell type check. Only the separate
  `test_refused_write_logs_the_error_type` covers them.
- `ERROR_TYPES` contains the bare word `"timeout"` (:115). A message like "read timeout" passed the hung row's
  "named a type" check before the fix too.

### S4 (should-fix). The public API snapshot pins names, not kinds or defaults
`_params` (test_public_api_snapshot.py:19-24) records parameter names only, and the Node snapshot records method names
only. Two kinds of break go unnoticed:
- a default change (the docs say `voice_session()` defaults must not change; `latency_budget_ms` default 250 is now a
  sentinel);
- a keyword-only parameter becoming positional, or a reorder.

The snapshot is generated by the SDK under test, but I checked it against the released `crowkis-sdk`
(feat/voice-adapters):
- Python: every released root name is present. The 7 differing shapes are supersets (new params, still keyword-only).
- Node: every released `index.js` and subpath export and method is present.

So no removal is hidden. Consider pinning `str(inspect.signature(...))`, or at least the parameter kind and default.

### Notes
- **Install (408ad84):**
  - test_install.py:27-33 swallows any `ImportError` in an `integrations` module. A packaging bug there (a missing
    internal file) would read as "optional missing".
  - The npm check uses `skipLibCheck: true`, so the package's own `.d.ts` files are not type-checked. Only the imports
    are.
  - The require scan matches double-quoted `require("./..")` only.
- **Cross-channel (untracked):**
  - The tests are sound and have real controls (same-channel serving, "first channel saved nothing").
  - The privacy half is close to tautological. The only shared write is the general answer, which has no secrets, and
    channels never serve each other (segments), so it reduces to "private turns are not written".
  - The real-server leak path, a shared answer that repeats a detail stated earlier (M1, M2), is not exercised. Add a
    case: intro, then the general question answered with the name, then check the writes.
  - Node sessions are never closed.
  - The whole file skips without `CROWKIS_CONFORMANCE_SERVER=1`. Expected, but it must be run before commit.
- **test_stated_name:**
  - The tests fail before the fix only via `ImportError` of `_stated_names`, which is weak evidence.
  - The controls are good: a general answer is saved, an unstated name is unaffected, "I'm looking for..." is not a name.
  - Chat has no spoken-phone case (M2).
- **Stress-bug classes (VD4/T11/VD8):**
  - They are real: I checked that baseline `decide('What is a PAN card used for?').rule == "CutOff"`.
  - The VD8 test asserts the model's `messages`, not the saved key. A key check against `store.writes` would be more
    direct.
- **Node vs Python fuzz:** the RNGs differ, so the "same seed" does not mean the same cases. Python `c-earlier`
  includes spoken phones and Node `c-earlier` does not (`digitsPhone`).
- **beb8647** changed an existing assertion (test_voice_stress_bugs.py:424, `assertIn` → `assertNotIn`). That is
  allowed, since it asserted the bug.
- **11a7244 (B4):** correct, timing only. The test now waits behind `SLOW_S = 2.0` in a background thread. Fine.
