# Ponytail audit: `python/crowkis/` on `feat/v4` (2026-11-01)

Read-only audit at `76239da`. Scope: `python/crowkis/` (158 files, 15,807 lines). Not in scope: `python/tests/`,
`fixtures/`, `node/`, `build/`. The owner's question: **did the refactor add too much abstraction, and are we on the
right path?**

**What this package does:** a client SDK for the Crowkis cache server. Its main job is the turn pipeline: for each
thing a caller says (voice) or types (chat), decide whether a cached answer may be served, and whether the model's
fresh answer may be shared with later callers, without one caller's private details reaching another.

**Load assumed:** one process serving many live calls at once (tens to a few hundred), each turn held to a lookup
budget of about 250 ms, against one Crowkis server that can be slow or hang.

---

## Verdict

**The direction is right. The abstraction that hurts is at the edges, not in the core.**

- **The core earns its abstraction.** `TurnCore` is 85 lines and reads top to bottom. Its 8 step interfaces
  (`turn_steps.py`) each have two implementations that really behave differently: voice returns a `TurnDecision`
  and keeps a transcript; chat returns a `TurnResult`, keeps a `CallState`, sends events and counts by name. I
  compared every voice/chat step pair. None differs only by a setting, so none should be merged. The rule chains
  (Chain of Responsibility, one rule per file) are the clearest part of the code.
- **The extra weight is around the core:** 11 small `Protocol`s (an interface type) that describe one class each;
  a 22-member `VoiceCall` interface with one implementation that mostly forwards calls; about 270 lines of private
  re-exports kept for import paths that no longer exist; and a few duplicated helpers.
- **How much should go:** about **4 to 11 files and 550 to 650 lines**, about 4% of the package. That is a short
  merge-and-delete pass, not a redesign. The package's real size is elsewhere: the word rules (about 2,900 lines,
  functions with cognitive complexity up to 80), `client.py` (2,050) and `channels/voice_session.py` (1,110).
- **What to stop:** three of P5.5's remaining items would *add* types and interfaces: item 4 (split `Verdict` into
  `EarlyAnswer` + `ChatVerdict`), item 5 (split `VoiceCall` into views, turn the chat `Protocol`s into injected
  objects) and item 6 (generics in `turn_steps`, an agent `Protocol`). That is the over-abstraction the owner is
  worried about. Do the deletions below instead.
- **P5.7 should be small.** Only 7 places outside `agent.py` call the raw client (`agent._client...`):
  `question_records.py` (2), `voice_session.report_stats` (1), `integrations/voice_turns.py` (4). Giving `Agent`
  four methods for them achieves "a server change touches one layer". A `transport/` package with one class per
  command family would be the largest new abstraction of the whole refactor, for a 2,050-line file that works and
  that no turn code touches. Split `client.py` only if someone has to change it.

**Recommended next step:** findings 1 to 5 as one pass in both languages (about a day), then stop P5.5. Keep items 8
and 11 of the clean-pass plan only where they are cheap (one confidence floor, one commitments table). Leave the
word-rule long methods until a misfire fix has to touch them, and then refactor that one function under the phrase
fixtures.

---

## Findings

Numbered across groups. No "must fix" findings: I found no bug that gives a wrong decision or leaks a caller's
detail on the normal path.

### Should fix

1. **Lookups that pass their deadline are never cancelled** (`runtime/cache_lookup.py:41`,
   `turns/session_call.py:100`, `runtime/question_records.py:75`, `runtime/deadline.py:16`)
   - **What this is:** each turn runs its cache lookup on a shared pool of 32 threads (`_LOOKUPS`) and waits up to
     the budget. Four places write this "submit, wait with a timeout" by hand. The helper `runtime/deadline.within`
     already exists and is used once.
   - **Problem:** on a timeout none of them cancels the job. When the server hangs (accepts, never answers), each
     lookup holds a thread for the client's 5 s read timeout. 32 threads handle about 6 lookups a second. At 50
     calls with a turn every 5 s (10 lookups a second) the queue grows by about 4 jobs a second for as long as the
     hang lasts. Calls are fine during the hang (they fall back to the model). After the server recovers, new
     lookups wait behind the old ones and miss their 250 ms budget, so hits are lost until the queue drains.
     `BudgetedUnderstanding` already cancels (`future.cancel()`); these four do not.
   - **Fix:** make `within()` cancel the future on timeout, and have the other three call `within()`. That removes
     three hand-written copies. The behaviour of a lookup that finishes in time does not change. Add one test: with
     a pool of 1 worker and a blocked job, a timed-out job that has not started never runs.
   - **If we skip it:** after every server hang under load, the cache stops serving for a while, and nothing in
     `stats()` shows why.

2. **About 270 lines of private re-exports protect import paths that no longer exist**
   (`channels/voice_session.py:38-~300`, `channels/call_session.py:52-71`)
   - **What this is:** `voice_session.py` re-exports about 255 private word-rule names "so
     `crowkis.channels.voice_session.<name>` keeps working". `call_session.py` re-exports about 20 more.
   - **Problem:** the old public path `crowkis.voice` was removed in P5.6 (`a1cba4b`, an owner exception; I checked
     that `import crowkis.voice` fails). `crowkis.channels.*` exists only on `feat/v4`, which has not been pushed
     (no remote branch contains `a1cba4b`) and is not released. So no outside code can depend on these names.
     Inside the repo only about 8 of them are read through the facade: `_words`, `_is_personal`,
     `_is_context_dependent`, `_PII_PLACEHOLDER`, `_instructs`, `_proper_nouns`, `_tells_about_caller`, and
     `_sets_context` (a `mock.patch` target in `test_voice_undecided_turns.py:107`). A quarter of the 1,110-line
     facade is this list.
   - **Fix:** delete both blocks. Import the few names the facades use themselves straight from
     `understanding.word_rules`, and point the handful of importers (`call_session.py:71`, the tests) there too.
     The mock target becomes `crowkis.understanding.word_rules...` or the module that calls it. This also makes
     clean-pass item 7's "one legacy module per facade" unnecessary. Before deleting, confirm with the owner that
     `crowkis.channels.*` has never been published.
   - **If we skip it:** every reader of the main facade scrolls past 260 lines of names, and P5.5 builds legacy
     modules for paths nobody uses.

3. **Eleven "what this class reads of the session" interfaces, each with one implementer**
   (`turns/app_hooks.py`, `chat_answers.py`, `chat_hit_check.py`, `chat_question_check.py`, `chat_reader.py`,
   `chat_report.py`, `chat_saving.py`, `chat_understanding.py`, `voice_pairing.py`, `voice_report.py`,
   `voice_saving.py`; about 105 lines)
   - **What this is:** each turn step takes `session` typed as a small `Protocol` (`ChatSessionBudget`,
     `ChatSessionState`, `VoiceSessionTranscript`, ...). A `Protocol` is a type that lists the members a class
     must have.
   - **Problem:** each has exactly one class that satisfies it (`CallSession` or `VoiceSession`). No test uses
     them. They look like decoupling, but every step still receives the whole session object and could read
     anything on it. `VoiceSessionTranscript` is even defined twice. Clean-pass item 5 would replace them with
     more injected objects, which adds pieces instead of removing them.
   - **Fix:** delete them and type `session` as `"CallSession"` / `"VoiceSession"` (imported under
     `TYPE_CHECKING`, so no import cycle). Where a step needs only one value, pass that value: `ChatHitCheck`
     needs only `latency_budget_ms`.
   - **If we skip it:** 11 more names for a newcomer to learn, and each new field read means editing an
     interface as well as the class.

4. **`VoiceCall` is a 22-member interface with one implementation that mostly forwards**
   (`turns/voice_call.py`, 85 lines; `turns/session_call.py`)
   - **What this is:** rules read the call through `VoiceCall`. Its only implementation is `SessionCall`. One test
     file fakes it by duck typing (any object with the right members works), so the test does not need the
     `Protocol`.
   - **Problem:** 13 of `SessionCall`'s members only hand the call on: 7 to `VoiceSession` properties, 6 to
     `CallReadings` (Fowler's Middle Man). It also writes the session's private fields `_tainted` and
     `_heard_texts` (Inappropriate Intimacy). Clean-pass item 5 would split it into several "views". That is more
     interfaces for one implementation.
   - **Fix:** delete `voice_call.py` and type rules with `SessionCall`. Move `tainted` and the heard turns into
     `SessionCall`, which then owns them; `VoiceSession` asks it. Keep the forwards for now: removing them would
     make rules write `turn.call.readings.is_personal(...)`, which is not clearer.
   - **If we skip it:** each new thing a rule needs is three edits (interface, forwarder, session), the Shotgun
     Surgery the "Splitting" rules warn about.

5. **`TurnResult` is a public class whose type hints crash** (`turns/turn_result.py:24`)
   - **What this is:** `TurnResult` is what `CallSession.handle()` returns (`from crowkis import TurnResult`).
   - **Problem:** `verdict: Optional[Verdict]` names a class the module never imports. I ran
     `typing.get_type_hints(TurnResult)`: it raises `NameError: name 'Verdict' is not defined`. Any app that reads
     hints crashes on it, for example a pydantic or FastAPI model that wraps the result, or API docs built with
     sphinx-autodoc-typehints. Importing the real class (`rules.rule_checker.Verdict`) would create an import
     cycle: `rules` imports `turns`.
   - **Fix:** `verdict: Optional[Any] = None  # RuleChecker's Verdict (rules imports turns)`. One line, plus a test
     that calls `get_type_hints` on every public class.
   - **If we skip it:** the first app that puts a `TurnResult` in a typed web response gets a crash at startup.

6. **The voice/chat save-rule twins: merge fewer than planned** (`rules/save/*`, `rules/question/stated_facts.py`,
   `voice_stated_facts.py`)
   - **What this is:** clean-pass item 12 merges 7 save-rule pairs and `StatedFacts` / `VoiceStatedFacts`.
   - **Problem:** the 7 save pairs do the same check, but they read different subjects (`ModelAnswer.answer` /
     `.key` against `ChatAnswer.text` / `.verdict.question`). Their rule names, reasons and counters are also public
     behaviour: they appear in decisions, `stats()["rules"]`, golden files and `without(["ChatEmptyAnswer"])`. So a
     merged class would still carry two names, two reasons and two counter sets, from a table. That saves about 60
     lines and adds one indirection. `StatedFacts` and `VoiceStatedFacts` are different algorithms (word-carrying
     check against relevance plus taint), so they are not twins.
   - **Fix:** keep the twins until `ModelAnswer` and `ChatAnswer` share one reading interface. Then merge only the
     four one-line checks (`EmptyAnswer`, `NonAnswer`, `ToolResult`, `ActionClaim`). Never merge `StatedFacts`.
   - **If we skip it:** nothing breaks. This is a warning against spending effort here.

7. **The same rule written in several places** (`frame_reading.py` and `rule_checker.py`: confidence floor 0.6;
   `rules/hit/commitment_policy.py` and `word_rules/phrases._COMMITMENTS`; `runtime/question_records.tenant_of`,
   `turns/session_call.agent_key:159` and `channels/call_session.py:271`: the same tenant `getattr` chain)
   - **Problem:** changing the floor in one place leaves the other at 0.6, so voice and chat would disagree about
     when a frame is "sure". The commitments table can drift the same way.
   - **Fix:** `RuleChecker`'s default reads `CONFIDENCE_FLOOR`; delete `commitment_policy.py` and read the one
     table; the two other places call `tenant_of(agent)`. That is -1 file and about -20 lines, with the golden
     files unchanged. The three stemmers and four `_EMAIL` patterns are the same problem but riskier:
     `frame_words._stem` feeds chat's `told=` key hash, so a different stem means lost cache entries. Merge them
     only where the golden files and phrase fixtures show no change.

8. **Two log lines write the server's error text** (`turns/voice_report.py:101`, `client.py:495`)
   - **Problem:** `voice_session.py:924` deliberately logs only the error *type*, because an error can quote
     personal text. These two log `str(error)`. A template write's key is the caller's own words for a personal
     turn. If a server refusal ever quotes the key, those words land in the app's logs. I found no server message
     that does this today (search below), so it is a risk, not a leak.
   - **Fix:** log `type(error).__name__` as `voice_session` does. `decision.not_stored` still carries the full
     text to the app. This changes a log line, so it needs the owner's go (progress notes, "Pre-existing").

### Nice to have

9. **`VoicePairing` is an adapter over a class only voice uses** (`turns/voice_pairing.py`, 42 lines)
   - `open()` is `begin()` + `start()`; `settle()` wraps `TurnPairing.settle` in a `Checked`. Chat's `ChatTurns`
     implements `Pairing` itself. Give `TurnPairing` the two `Pairing` methods (renaming its own
     `settle(turn)` to `settle_turn`) and delete the file: -1 file, about -30 lines. Low value, low risk.

10. **Type the hit once, at the lookup** (`runtime/cache_lookup.py`, `turns/voice_report.py:73,84`,
    `turns/chat_hit_check.py:43`, `turns/chat_report.py:432`)
    - `Hit.from_agent` exists, but three readers still index the raw dict (`looked.hit["confidence"]`,
      `hit.get("route")`). Build the `Hit` in `CacheLookup.find` and pass it on. This is the useful part of
      clean-pass item 6. The rest of item 6 (generics, an agent `Protocol`) adds types for no caller.

11. **Report's `refused` is not part of the core's contract** (`turns/turn_steps.py:84`)
    - `TurnCore` never calls `report.refused`; only the channel's own `Saving` does. Drop it from the `Report`
      `Protocol` so the interface lists what the core really calls.

12. **`Channel`'s three unused fields: do not delete them** (`turns/channel.py`)
    - Clean-pass item 15 removes `isolates_context`, `audio` and `saves_answers` because nothing reads them. But
      `Channel` is public (`from crowkis import Channel`) and those are required constructor arguments, so
      deleting them breaks any app that builds its own `Channel(...)`. At most give them defaults. Leave the class
      as it is.

Left out: about 10 smaller items (`Any` annotations, names with a leading `_` imported across packages, the
`"crowkis voice:"` log prefix on chat writes, `CacheLookup`'s "voice budget" wording on chat). They are cosmetic,
and clean-pass already lists them.

### Checked and fine

- **Speed:** I counted the word-rule calls in one voice turn with a fake agent (scratch script, no code changed).
  A first turn runs `_is_personal` 5 times in decide; a follow-up runs it 11 times. The whole decide takes 0.5 to
  0.8 ms. The repeated work costs nothing next to a 250 ms budget, so there is nothing to cache.
- **Error boundaries:** writes (`BoundedWriter.write_within`), lookups (`CacheLookup`), voice understanding
  (`BudgetedUnderstanding`), chat understanding (`ChatUnderstanding`) and app hooks (`AppHooks`) each have one
  catch site that counts what it catches. These are good.
- **Privacy defaults:** an unsure or late model reads as personal (`FrameReading.is_personal`, the fallback to the
  word rules), and `CallReadings` lets a plugged-in classifier only add privacy.

---

## Can a newcomer follow one voice turn?

`VoiceSession.decide("what are your opening hours on sunday")`, then `record(decision, answer)`, with no
understander plugged in (the default).

**decide (17 plumbing files, plus the leaf rules):**

1. `channels/voice_session.py` `decide` →
2. `turns/turn_core.py` `decide` →
3. `turns/voice_pairing.py` `open` → 4. `runtime/turn_pairing.py` `begin` / `start`
5. `turns/voice_report.py` `before_reading` (always None for voice)
6. `turns/voice_reader.py` `read` → 7. `understanding/word_rule_classifier.py` →
   8. `understanding/rewrite_check.py`, 9. `understanding/no_rewrite.py` → 10. `understanding/call_readings.py`
   `note` → 11. `turns/voice_turn.py`
12. `rules/rule_set.py` `check_question` → 13. `rules/chain.py` → 9 question-rule files → reading
    14. `turns/session_call.py` (typed as 15. `turns/voice_call.py`)
16. `runtime/cache_lookup.py` `find` → `agent.py` `ask` → `client.py`
17. `turns/hit.py`, `turns/cached_answer.py` → 7 hit-rule files (`DifferentQuestion` →
    `runtime/question_records.py`)
18. back in `voice_report.py`: `served` / `missed` / `to_model` → `turns/decision.py`; value objects from
    `turns/checked.py` and `turns/verdict.py`

**record (8 more plumbing files):** `voice_session.record` → `_record_decision` → `_record_model_turn` →
`turns/answered.py` (`VoiceAnswered`) → `turn_core.record` → `voice_pairing.settle` → `turns/voice_saving.py`
`check` → `turns/model_answer.py` → save chains (1 + 3 + 5 rule files, or `personal_template.py`) →
`voice_saving.write` → `runtime/bounded_writer.py` → `runtime/write_workers.py` → `runtime/write_result.py` →
`question_records.keep` → `voice_report.kept` / `recorded` → `turns/outcome.py`.

**Count:** about 25 plumbing files and about 25 leaf rule files for one full turn. The deepest call stack is 9
frames (`decide` → `TurnCore.decide` → `look_up` → `RuleSet.check_hit` → `RuleChain` → `DifferentQuestion` →
`SessionCall` → `QuestionRecords` → `client.get`). The order is easy to follow because `TurnCore` names each step.
What slows a reader is the jumps sideways: `VoiceCall` to `SessionCall` to `CallReadings` or `VoiceSession` for one
answer, and `VoiceReport`, which plays three parts (Report, EarlyAnswers, and the model-messages privacy check).
Findings 3, 4 and 9 remove 3 of the 25 files and most of those sideways jumps. A one-page "turn walk" in P5.8's docs
would help more than any further split.

---

## Where this agrees and disagrees with `clean-pass.md`

| Clean-pass item | This audit | Why |
|---|---|---|
| 1 parity, 2 `Outcome` / `WriteResult`, 3 error boundaries (done parts) | **Agree** | These removed real duplication and gave each concern one catch site. |
| 3 left: `realtime` fallback count, `engine_vouches` deadline | **Agree, plus** cancel on timeout | Finding 1: fold all hand-written deadlines into `within()` and cancel. |
| 4 `Verdict` one job (`EarlyAnswer`, `ChatVerdict`) | **Disagree** | Adds two types and touches 4 rules to split a 6-field frozen dataclass. Nothing breaks today. |
| 5 narrow host / session interfaces (split `VoiceCall`, chat `Protocol`s to injected objects) | **Disagree on the method, agree on the smell** | Delete the one-implementation interfaces (findings 3, 4); do not split them into more. |
| 6 no `Any` (generics, agent `Protocol`, typed `Hit`) | **Partly** | Typed `Hit` yes (finding 10), and fix `TurnResult` (finding 5). Generics and an agent `Protocol` add types with one user. |
| 7 no private names across packages; legacy module per facade | **Partly** | Delete the facades' re-exports outright (finding 2); no legacy modules for paths that never shipped. A public interface for `word_rules` is fine, but low priority. |
| 8 one stemmer, one copy of each pattern | **Agree, carefully** | Finding 7: the stemmer feeds a key hash, so only merge where golden is unchanged. |
| 9 P4 rough edges | **Agree (small)** | `rewritten: Optional[str]` checked once is cheap. A new counter is an owner decision. |
| 10 one counting system | **Neutral** | Real duplication, but chat's `counts` dict is public. Worth it only together with another chat stats change. |
| 11 one place per key part / threshold | **Agree** | Finding 7. Cheap and safe. |
| 12 merge voice / chat pairs | **Mostly disagree** | Finding 6: the turn-step pairs really differ; the save twins carry public names; `StatedFacts` pair is two algorithms. |
| 13 long methods in the word rules | **Agree on the problem, not the timing** | This is the package's biggest readability cost (cognitive up to 80). Do it per function when a misfire fix touches it, under the phrase fixtures, not as a sweep. |
| 14 split `VoiceSession` | **Agree after finding 2** | Deleting the re-exports takes it from 1,110 to about 850 lines; then moving `VoiceResponse` / `warm_from_calls` out is optional. |
| 15 leftovers (`Channel` fields, ...) | **Disagree on `Channel`** | Finding 12: public constructor arguments. The rest is fine. |
| Inventory: "46 clean, 101 not clean" | **Overstates it** | Most "not clean" marks are `Any` annotations and `_`-prefixed imports. Only about 10 files have a problem a user or maintainer would feel. |

---

## Estimate: what a merge pass removes (Python; Node mirrors it)

| Finding | Files | Lines |
|---|---|---|
| 2 private re-exports in the facades | 0 | -270 |
| 3 eleven one-implementation `Protocol`s | 0 | -105 |
| 4 `VoiceCall` interface | -1 | -85 |
| 1 hand-written deadlines into `within()` | 0 | -10 (and a load fix) |
| 7 duplicate floor, commitments table, tenant lookup | -1 | -20 |
| 9 `VoicePairing` into `TurnPairing` | -1 | -30 |
| 5, 10, 11 small fixes | 0 | about -10 |
| **Pass without the save twins** | **-3 to -4** | **about -530 to -560** |
| 6 the four one-line save twins, later | -4 more (-7 if all) | about -60 |
| **Upper bound** | **about -11** | **about -620 (4% of 15,807)** |

No dependencies to remove: the package needs only the standard library at runtime (the frameworks are extras).

Lean: -560 lines, -0 dependencies possible (up to -620 with the save twins).

**Not checked:** `node/` (assumed to mirror the same design, as asked); `client.py`, `grpc_stub.py`,
`openai_wrapper.py` and the integrations were only skimmed for raw-client use and logging, not audited line by
line; the word-rule modules' phrase logic (covered by the phrase fixtures); no test suite was run and no real
server was used. For finding 8, a grep of `../crowkis/kern` for `ERR` messages that format a key found none, which
is not proof that none exists. Graphify was not used; callers were found with grep. The claim in finding 2 that
`crowkis.channels.*` never shipped rests on `feat/v4` having no remote branch: the owner should confirm it.
