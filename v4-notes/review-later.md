# Review once v4 is complete

The owner's list for a whole-codebase review after the refactor (decided 2026-10-22: let the phases run as
planned, review cleanliness at the end). Nothing here is scheduled in a phase.

## 1. Two turn flows, not one core

P3 put Chat's flow in its own `ChatCore` (`turns/chat_core.py`, `src/turns/chatCore.js`) beside voice's
`TurnCore`. They share the rules and the runtime pieces, but the plan's P3 goal was one core ("`CallSession` and
`Chat` become facades on `TurnCore`"; done when "one rule set serves both facades"). The session left the merge
to P5 because Chat's steps need generalising first. Two flows can drift apart again, which is what v4 exists to end.

## 2. `TurnCore` findings (read 2026-10-22, `turns/turn_core.py` and `turns/turn_host.py`)

1. `TurnHost` bundles about six jobs: transcript, agent, settings (`serve_above`, `latency_budget_ms`, `ttl`),
   audio, writes (`learn`, `learn_personal`), question records (`keep_question`, `note_stored`), keys
   (`context_key`). Split into small pieces (`Transcript`, `CallSettings`, `AudioClips`, `CacheKey`) and inject
   the writer directly.
2. The lookup calls the raw agent (`self._host.agent.ask(...)` in a lambda with `noqa`), with a magic `0.60`
   and threshold logic inline, and returns a raw dict as `Tuple[Optional[dict], Optional[Verdict]]`. Wanted: a
   typed `Hit` from `transport/`; the lookup settings in `CacheLookup`.
3. Outcomes and routes are string literals (`"serve"`, `"infer"`, `"interrupted"`, `"saved"`, `"template"`,
   `"refused"`, `"WriteRefused"`, `"Interrupted"`); `_Outcome` is a private `str` subclass. The plan's §3.5 asks
   for an `Outcome` enum.
4. `record()` is about 35 lines: pairing, building the answer, three chains, the transcript, the personal
   branch, the write, question records and error handling. Split into named steps.
5. The write's error boundary (`except Exception`) is inside `TurnCore`. P2 said the lookup and write
   boundaries are the only catch sites: it belongs in `BoundedWriter`, which should return a typed `WriteResult`.
6. Mixed return values: `learn()` returns `None` or an outcome, `learn_personal()` returns `True` / `False` /
   an outcome, hence `isinstance(templated, _Outcome)`.
7. Seven ad-hoc chains (`before_filler`, `filler`, `question`, `answer_given`, `before_sharing`, `sharing`,
   `personal` with its own `.check()` / `.refusal()` API) instead of the three stages.
8. The transcript is a bare list of dicts, appended in two places with copy-pasted pairs.
9. Private attributes set after construction: `decision._audio_shareable = ...`.
10. Still voice-shaped: `VoiceTurn`, `VoiceCall`, `voiced()`.
11. A private import across packages: `_CONTEXT_BOUND_THRESHOLD` from `word_rules`.

Why they got through: each phase's "done when" only checks behaviour (golden identical, suites green). Code
that moves without being redesigned passes every gate.

## 3. Other things to look at

- Save rules kept in pairs while behaviour mustn't change: `chat_empty_answer` / `empty_answer`,
  `chat_non_answer` / `non_answer`, `chat_prompt_details` / `prompt_caller_details`. P5 merges the save check.
- `understanding/word_rules/personal.py` (about 770 lines) and `text.py` (about 600): moved unchanged; P4 puts
  them behind `WordRuleClassifier`.
- `understanding/frame_words.py`, `slots.py`, `answer_patterns.py`: check they are real named pieces, not helpers.
- Rules import private `word_rules` functions and read the raw hit dict (`cached.hit.get("commitment")`):
  planned for P4 (classifier, typed `Hit`).

## 4. Practices to borrow for the review

- Fowler, *Refactoring*: the code-smell catalogue as the checklist (Long Method, Large Class, Primitive
  Obsession, Inappropriate Intimacy, Data Clumps, Message Chains, Middle Man, Speculative Generality).
- Kent Beck's four rules of simple design, in order: passes the tests, reveals intention, no duplication,
  fewest elements (the last one guards against over-splitting).
- Ousterhout, *A Philosophy of Software Design*: deep modules (a small interface hiding real work); avoid
  "classitis" and classes that only forward calls.
- Google's style guides and code-review guide: "is it more complex than it needs to be?"
- YAGNI / KISS: an interface only when a second implementation exists or is planned.
- Measure, not opinion: cognitive complexity (default limit 15 per function), the ruff / eslint default
  limits, change amplification (files touched for 5 typical tasks, before vs after), a newcomer test, and a
  count of forward-only classes.

## 5. P4 review fixes (commits `91ab247`, `0f5aae3`), read 2026-10-23

Root-cause fixes, with tests (`test_rewrite_safety.py`, 135 lines). Details to clean in P5.5:
- `understanding/rewrite_check.py` imports five private `word_rules` functions (`_is_personal`, `_leaks`,
  `_numbers`, `_proper_nouns`, `_words`).
- `RewriteCheck._stem` is a new, crude stemmer (`lower().rstrip("s")`: "news" -> "new", "bus" -> "bu"), beside
  the existing N2 stemmer. Use one stemmer.
- `RewriteCheck.accept(..., rewritten: object, ...)` with an `isinstance` check: validate the rewriter's
  result once at the boundary (`BudgetedUnderstanding`) and type it as `Optional[str]`.
- `BudgetedUnderstanding` raises `TimeoutError` when its in-flight limit is full, so "too many model calls
  waiting" is counted as `understand_timeouts`. Give it its own counter and outcome.
- `TurnCore` builds a default `RewriteCheck()` itself; collaborators come from the composition root.
- `VoiceCall` / `SessionCall` keep growing (`is_context_dependent` added), the same host-interface concern
  as section 2.

## 6. Merge similar voice / chat pairs (owner, 2026-10-24)

P5.5 splits each turn step into a voice part and a chat part (`turns/voice_*.py` / `turns/chat_*.py`, behind the
interfaces in `turns/turn_steps.py`). Once the refactor is done, compare each pair side by side:
- **Mostly the same, with the differences being settings:** merge them into one class that reads the channel
  profile (`turns/channel.py`), and move the settings into the profile (Fowler's Inline Class / Collapse Hierarchy).
- **Really different behaviour** (Chat reporting every objection vs voice stopping at the first, Chat's routes,
  voice's barge-in and audio): keep them split.
The pieces are internal (apps only use the facades), so a merge changes no public name. Merge in both languages,
combine the two classes' tests, and keep golden decisions identical.

Also from the 2026-10-24 tour: `VoiceSession.decide()` still numbers the turn, offers sharing and builds
`decision.messages` (`_model_messages`) around the core. That belongs in the core's steps (pairing, report), so the
facade's `decide()` only calls the core.
