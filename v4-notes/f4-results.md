# F4: stress-run proof of v4 (IN PROGRESS, paused 2026-11-02)

Script: `v4-notes/stress/voice_stress_test.py` (copy of the owner's, with a `v4` pipeline; `--pipeline all` runs voice, chat, v4).
Results are in `v4-notes/stress/results/` (git-ignored).

## Status
- `voice` (groq pipeline): complete, 33 calls / 239 turns, not yet judged.
- `chat`: 11 of 33 calls played, then Groq `qwen/qwen3.8-27b` hit its **200k tokens/day** limit.
- `v4`: not started. Needs the same understanding model.
- One understanding turn costs about 2.2k tokens, so chat + v4 need roughly 1M tokens: about 5 days on this model's free quota.

## Open decision
Use another Groq model for the understanding step (same one for chat and v4, chat replayed from scratch), or spend ~5 days of quota
on qwen. `crowkis-demo` is stopped; resume with `--resume` (starts it again, tenant `voice` is flushed per pipeline).
