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
| Add a question rule | | |
| Change a threshold (the confidence floor) | | |
| Add a counter | | |
| Change a key part (the knowledge segment) | | |
| Fix a misfire (a word list) | | |

## Inventory

Each file: clean, or not clean with the reason, and the commit that made it clean.
