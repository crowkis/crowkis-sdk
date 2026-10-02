# Changelog

## Node: turn understanding (unreleased)

Turn understanding v2.2 for Node, mirroring Python (same rules, same tests). Additive:
`Conversation` and `VoiceSession` are unchanged.

### Added
- `turn.js` (`TurnFrame`), `callstate.js` (`CallState`), `verify.js` (`RuleChecker`, `Verdict`),
  `understand.js` (`LLMUnderstander`, `ReplayUnderstander`, `WithFallback`), `session.js`
  (`CallSession`, `TurnResult`), `callbridge.js` (`CallBridge`, framework-free voice pipeline logic).
- Async throughout: `handle`, `recordAnswer`, understanders and the bridge return promises;
  understanding and lookup run under hard time limits (`understandBudgetMs`, `latencyBudgetMs`).
- Exports from the package root and subpaths (`@crowkis/client/session`, `/verify`, ...),
  TypeScript declarations, `npm test` script, README section.
- `test-call-session.js`: 25 tests.

### Known
- `test-voice.js` "node classifier agrees with the python classifier" needs `python3` on PATH;
  it fails on Windows where only `python` exists (pre-existing, unrelated to this change).

### Fixed (both SDKs)
- A turn the model abstains on now always clears the active question, even with no details
  (it was skipped as a plain acknowledgement).

## Python: turn understanding (unreleased)

Turn understanding v2.2: decide what may be shared from the *meaning* of each caller turn,
checked by fixed rules, instead of from word lists. Additive: `Conversation` and `VoiceSession`
are unchanged.

### Added
- `CallSession`: one call or chat thread. Per turn: understand → rule checker → route
  (`urgent`, `task`, `shared`, `personal`, `tools`, `agent`) → bounded lookup → answer →
  save check → call-state update.
- `TurnFrame`: the structured description of a turn (kind, subject, urgent, task step, typed
  entities, tier/location with `changes_answer`, standalone question, question type).
  Fail-closed parsing; an entity's type decides whether it identifies someone.
- `CallState`: per-call memory as structure, not transcript: active question, details,
  agent mentions, task status, tier/location, identity level (set by the app). Fillers never
  change it; nothing identifying is stored; the snapshot sent onward has no caller transcript.
- `RuleChecker`: V1-V9 (urgent, uncertainty, not general, about someone, identifying details,
  grounding, lost details, relevant attributes only, task steps) and the key builder
  (location on place questions and searches, expiry by question type, knowledge version).
- Understanding slot: `LLMUnderstander` (interim, any provider), `ReplayUnderstander`
  (exact repeats of verified questions only), `WithFallback`.
- Hard time limits on understanding (`understand_budget_ms`) and lookup (`latency_budget_ms`);
  a late result is discarded and the safe fallback or the agent takes over.
- Personal answer contract: `register_shape` / `phrase` phrase a value the app's own tools
  returned, only at the required identity level and never for someone else.
- Save check: non-answers, identifying details, action claims ("I've cancelled it") and tier or
  location values not in the key are never saved.
- Production controls: `set_mode("off" | "replay_only" | "full")` kill switch, `on_event`
  monitoring hook (no raw caller words), `stats()`.
- Barge-in: cancelled or superseded turns are never saved.
- `crowkis.integrations.call_bridge.CallBridge` (framework-free voice logic) and
  `crowkis.integrations.pipecat_call.call_processors` (Pipecat). Fixes over the 0.5.2 Pipecat
  processors: the system prompt and tools survive a miss; audio is cached only for shared
  answers, recorded whole, never re-recorded from playback, keyed by voice, sample rate and format;
  every cache call is bounded and wrapped.
- Example: `python/examples/call_session_agent.py`.

### Fixed (docs)
- README `Conversation` example no longer calls the model and saves over a cache hit.
- README no longer claims the server mirrors the SDK word rules.

### Evidence
- Synthetic suite (6,720 generated cases, 640 run through the built `CallSession`): with a
  Sonnet-class stand-in model, 0 failures; with Haiku-class, 97 (mostly lost hits), 5 wrongly shared.
- Real conversations (Taskmaster-2 + ABCD, 690 caller turns): 4.7% and 3.8% of turns wrong on the
  two sets, versus 45-48% for `Conversation`; caller-identifying details in a shared key: 0.

### Not yet
- Node SDK equivalent.
- Pipecat processors are tested against `pipecat-ai` 1.12.0 at frame level (gate, writeback,
  audio, full save-and-replay turn); not yet in a live call with real audio.
- A production turn-understanding model (server `CTURN`, or a local model) to replace the interim adapter.
