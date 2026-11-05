# Speed check: why F6's voice-pipeline decide p95 was 68 ms (2026-11-05)

**Question:** with no understander plugged in, v4's decide p95 was 12 ms in F4b and 68 ms in F6. Is it v4 or the server?

**Answer: neither the SDK nor a newer server. It is the first pass over new questions on a fresh container.** The Crowkis server takes about 25 ms to look up a question it has never seen, and about 1 ms for one it has seen. The old SDK is just as slow as v4 when it goes first. No v4 bug found; nothing added to `open-items.md`.

## Setup
- Old SDK `feat/voice-adapters` (`e596e5a`, a worktree) and v4 `feat/v4` (`6e936cf`): one Python 3.12 venv each, Pipecat 1.12.0, editable installs, run from outside `D:\Tarkova`.
- Servers, fresh data, Community edition, each on its own ports: `crowkis:0.5.2-dce94b4` (F6's) and `crowkis:0.5.2-2c570ee` (what `crowkis-demo` runs now). **The `6ecdb9b` image (F4b's) does not exist locally**, so `2c570ee` is the second server and is not F4b's build.
- Run: `voice_stress_test.py --pipeline groq --no-judge`, the 33 default calls (239 turns), Bedrock `gpt-oss-20b` as the answerer. Scratch copies of the script: path-only patches (cross-drive `relpath`, the spend file kept at the real one). The old SDK uses the agent's own `reports.py` because the v4 copy imports `crowkis.privacy`.
- "Decide" is `gate_ms`: the Pipecat gate's time around `session.decide`, run on the server thread pool. Nearest-rank percentiles over 239 turns.
- Bedrock spend: 1.588 USD before, **1.787 after** (cap 2.00, script stop 1.90, not raised). About 0.03 per run.

## Decide, per run (239 turns each)

| Order on the container | Server | SDK | p50 | p95 | max | turns > 20 ms |
|---|---|---|---|---|---|---|
| 1st (fresh) | dce94b4 | v4 | 0.9 | **25.5** | 39.2 | 58 |
| 2nd | dce94b4 | old | 0.8 | 3.9 | 23.7 | 3 |
| 1st (fresh, again) | dce94b4 | old | 0.7 | **47.9** | 55.2 | 67 |
| 2nd | dce94b4 | v4 | 0.9 | 5.1 | 47.1 | 9 |
| 1st (fresh) | 2c570ee | v4 | 0.9 | **27.4** | 48.1 | 58 |
| 2nd | 2c570ee | old | 0.6 | 3.6 | 25.1 | 4 |

Whichever SDK runs first on a fresh container is slow; whichever runs second is fast. Same call set, so the second run asks the questions the first already asked. The two servers behave alike.

The seventh run (old SDK first on a fresh `2c570ee`) stalled in a Bedrock call after 12 calls and was stopped; the v4-second run on `2c570ee` was not run.

Caveat: the first v4 run on `dce94b4` overlapped for about two minutes with a crashed stray run on the other server (same machine), and the machine's other load was not controlled. Not enough to explain 58 slow turns.

## Server lookup against SDK work

- **Raw lookups, no stress script** (`CGET` through the plain client against `decide`, 600 turns per run, repeated questions): lookup p50/p95 0.7 / 0.9-1.1 ms; decide 1.1 / 1.5 ms for the old SDK and 1.4-1.5 / 2.1 ms for v4. **v4's own work is about 0.4 ms more than the old SDK's.** The one slow run (v4's first on a fresh `dce94b4`) was slow in the raw lookup too (p95 23 ms), so the time was the server's.
- **Per-command trace** of the 239 caller lines through `decide` / `record`: both SDKs send the same 71 lookups and no other command (v4: 62 serve + 9 infer; old: 59 serve + 12 infer), and every decide over 15 ms was a single `CGET` of 26-39 ms. The SDK's share of a slow turn was under 3 ms.
- **The server's cost:** `CGET` of a never-seen question took 22-26 ms every time (a probe issuing new misses 150 ms apart on `dce94b4`), against 0.7 ms for one asked before. That looks like the query's embedding being computed once and kept; not checked in the server code.
- **Why F4b looked fast:** its voice run was not the first on that server, so the questions had been seen. F6 was a fresh container, so its first run paid 25 ms per question. Both F6's p95 of 68 ms (33 calls) and 118 ms (40 calls) were first passes; this run's first passes are 25-48 ms, so the numbers differ but the cause is the same (F6's also had two runs sharing a machine, and a judge run alongside).

## Conclusion
- **Not v4:** the old SDK is as slow on a first pass (47.9 ms) and v4 as fast on a second (5.1 ms).
- **Not the newer server:** the older build `2c570ee` shows the same pattern.
- **A cold-container / first-sight effect on the server** (about 25 ms for a question it has not looked up before), which a fair comparison must remove by giving every SDK the same warm-up, or by alternating the order.
- For a live call this means the first caller to ask a new question can wait about 25 ms in the lookup, inside the 250 ms budget. Worth telling the server team; not an SDK change.

Scratch scripts (not committed): bench, trace, stall and run drivers under the session scratchpad.
