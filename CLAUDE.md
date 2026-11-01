# Crowkis SDK v4 — rules for working here

The SDK runs inside customers' production apps, including live voice calls. Nothing that already
works may break. **Functionality first:** a change is done when it works, is tested and keeps every
caller's private details private, not when it is elegant.

## 1. Find the place through the graph, then change only that

- Use the knowledge graph first (`graphify-out/`, built from the code). The command is not on PATH:
  `G=C:/Users/j7goe/AppData/Roaming/Python/Python314/Scripts/graphify.exe`
  - `$G query "<what you are looking for>"`, `$G explain "<path>::<Name>"`,
    `$G path "<A>" "<B>"`; `graphify-out/GRAPH_REPORT.md` for the overview.
  - After changing code: `$G update .` (seconds, no model).
- Read the files the graph points to before editing; grep every caller.
- Change only what the task needs. Smallest root-cause fix; no drive-by refactors.
- Public names and behaviour stay as they are (`from crowkis import voice_session, VoiceSession,
  Chat, CallSession, TurnResult, ...`), except where the owner has made an exception in
  `../sdk-docs/v4-refactor-plan.md` (P5.6 removed the old module paths). Python and Node change
  together and stay in parity.

## 2. Prove it with tests

- A test that fails before the change and passes after it, for every behaviour changed or fixed,
  in both Python and Node, plus "must still work" controls for the opposite case.
- Golden decisions (`fixtures/golden/`) stay identical unless the task is a behaviour change the
  owner approved; then list every changed decision by rule.
- Edge cases that apply: empty, very long, Unicode and non-Latin text, Hinglish, numbers with
  separators or in words, concurrent calls, server errors and a hung server.
- Privacy: a caller's private detail must never reach another caller. When unsure, keep it private.
- Existing tests are not edited to make a change pass, unless they asserted the bug (say which).
- Run the full Python and Node suites, more than once; the three frameworks (Pipecat, LiveKit
  Python, LiveKit JS) and Bolna for anything an adapter touches.

## 3. Review, then commit

- One review per phase by Opus (correctness and privacy), and a real-server check for anything a
  caller would notice (`crowkis-demo`, tenant `voice`, never flush, stop it afterwards).
- No co-author trailer in commits. Nothing is pushed until the owner says so.

## 4. How to write code here (ponytail)

- **Smallest complete change** (ponytail `full`): does it need to exist? Is it already in the
  codebase? Then the minimum code that works, finishing every caller, test and fixture it touches.
- **Don't OOPify.** No new classes, interfaces (`Protocol`s), wrappers, layers, options or
  "for later" code unless the task cannot work without them. A function is fine. Two real
  implementations that behave differently are the minimum for a new interface.
- **Keep the structure that exists** (folders, the one turn core, one rule per file in
  `rules/<stage>/`). Don't restructure code you aren't changing; don't merge or split files as a
  side effect.
- Deletion beats addition. Duplicated logic is fixed once, in the shared place, so every channel
  gets the fix.
- A live call never ends because of Crowkis: a failure becomes an outcome and a count in `stats()`,
  not an exception into the call. Log the error *type*, never text that could quote a caller.
- No magic thresholds scattered around: one named constant per value.
- Comment only the why, in one line. A shortcut with a known limit says so:
  `shortcut: <the limit>, <when to upgrade>`.

## 5. How the work runs

- **One fresh, throwaway session per phase or feature,** started from a short brief and
  `v4-notes/progress.md`. It does that one job, updates `v4-notes/progress.md` (what was done,
  commits, what is next) and ends. No long-running sessions.
- **Models:** Opus plans and reviews; Sonnet (normal) writes logic; Sonnet (low) does mechanical
  work (merges of moved code, imports, fixtures, test runs).
- **Usage limits (owner, hard lines):** the 5-hour limit never goes above **95%**, and the weekly
  limit never above **50%**. Check usage (`mcp__ccd_session_mgmt__get_usage`) before each step; if
  the next step could cross either line, stop at a committed, green point and record where it
  stopped in `v4-notes/progress.md`. For the 5-hour line, wait for its reset (a background timer,
  no polling) and continue; for the weekly line, stop and leave it to the owner.
- **Order of work** (`../sdk-docs/v4-refactor-plan.md`): F1 bring in `feat/voice-adapters`, F2 one
  call state and one key builder, F3 SDK bug fixes, F4 stress-run proof, F5 merge into
  `crowkis-sdk`. Polishing phases come after, only if the owner asks.
