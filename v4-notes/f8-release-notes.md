# 0.6.0 release notes (F8): one front end, one rule set, one pool

## Behaviour
- Chat runs on the voice front end: `voice_session(channel="chat")` (Python), `voiceSession({channel: "chat"})` (Node): one rule set, 1 s lookup budget, not spoken, no audio.
- One cache pool per tenant: the segment is `kb=<knowledge_version>` for every session, with or without an understander. Voice and chat share answers. **One-time cold cache:** answers saved by an older SDK (no segment, or `kb=..;channel=..`, or Chat's `kb=..;lang=..;channel=chat`) are not found; the pool refills with use.
- Screen-only answers (tables, links, code) saved on chat are served on chat, not spoken on voice (`ScreenOnlyAnswer`).
- New protections on both channels: a caller's private words never reach a shared answer in any mode (`VoicePrivateWord` in the base set); a question naming a person ("named Rahul", "asks Anita", "did Priya order") and a question holding a link are kept private.

## Removed public names
- Python: `Chat`, `ChatReply`, `ChatConflict`, `MemoryStore`, `CallSession`, `TurnResult`, `RuleChecker`, `Verdict` (the rule checker's), `ReplayUnderstander`, `ReplayRewriter`.
- Node: `Chat`, `ChatConflict`, `MemoryStore`, `CallSession`, `TurnResult`, `RuleChecker`, `Verdict`, `ReplayUnderstander`, `ReplayRewriter`; types `CallSessionOptions`, `ChatOptions`, `ChatReply`, `ChatStore`, `RuleCheckerOptions`; subpaths `@crowkis/client/chat` and `@crowkis/client/session`.
- Also removed: `knowledge_segment` helpers `key`, `key_attributes`, `told` (Python `crowkis.keys`).
- Kept on purpose: `LLMClassifier`, `LLMRewriter`, `TurnFrame`, `accepted_rewrite`, `stated_fact_irrelevant`, and (deviation from the plan) `LLMUnderstander`, `WithFallback`, `CallState`: the only way to plug a model into `LLMClassifier`, and voice tests use them.

## Migrating from Chat
Replace `Chat(...).turn(thread, history, answer=model)` with a `voice_session(channel="chat")` per thread: `decision = session.decide(text)`; if `decision.needs_model`, call your model with `decision.messages` (or the whole thread when it is `None`) and `session.record(decision, answer)`.
