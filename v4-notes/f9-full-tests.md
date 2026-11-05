# F9: full tests (2026-11-05/06) — PARTIAL

**Server:** `crowkis:0.5.2-dce94b4`, container `crowkis-f9` (fresh data, ports 7393–7396, Community edition, built-in judge `judge=crowjudge match=ABSENT`, no Bedrock settings on the server). **SDK:** `feat/v4`.
**Bedrock spent (script answerer, understanding, judge): 3.67 USD** (cap 5.00, stop 4.90; 1.80 before F9).

## What is done / not done

| Part | Status |
|---|---|
| B1 conformance on the real server, system Python | **pass** (9 passed, 27 skipped) |
| B1 conformance, Node | **pass** (9) |
| B1 conformance, Pipecat / LiveKit Py / Bolna / Node+LiveKit JS | **not run** (weekly budget) |
| B2 cross-channel server tests, Python and Node | **pass**: voice and chat share general answers on one tenant (both directions, plus chat→chat and voice→voice controls); private details and answers repeating stated details are not shared |
| B3 other server-marked tests, examples, website snippets on the server; B4 wrong token / server stopped mid-call / slow writes | **not run** |
| A: offline suites | one pass each: Python 797 passed, 138 skipped; Node 64/65 files (the failure is `test-voice.js` "the node classifier agrees with the python classifier on all 44", needs `python3` on PATH; not investigated). Second pass, slow tests, frameworks, part-by-part coverage list: **not run** |
| C: stress, all 73 calls (below) | **done** |
| D: voice demo | **not done** |

## Bugs fixed

- **Real-server conformance fixture** (06e39f6): the server's write pipeline rejects short or digit-heavy answers ("security pipeline … composite 0.73–0.74"), so the "reworded question hits" and "Unicode, Hinglish and numbers" scenarios never stored their answers and the next caller missed. Three fixture answers lengthened (dark mode, Hinglish refund, Spanish hours). Not an SDK bug; no failing-first test.
- **Stress script** (bb1839c + follow-up): `chat` pipeline now = `voice_session(channel="chat")`, word rules only; Bedrock stop 4.90. The first edit silently failed (CRLF), so the first "chat" run (`145624`) was really v4 inline with the classifier: its gate p50 560 / p95 886 ms was the understanding model (`understand_ms` ≈ `gate_ms`), not the chat path. **That run is void; B2 is the chat run.** Direct timing of the chat channel against the server: fillers and private turns 0.1–0.6 ms, lookups 2–55 ms. So the SDK chat path has no latency bug.

## Server findings (not added to open-items.md yet)

- The write pipeline's score (composite ~0.73 < threshold) refuses short, digit-heavy answers, e.g. "Abrimos de 9 a 18 h, de lunes a sábado, y cerramos los domingos y festivos." — a normal opening-hours answer. Customers' short factual answers are not cached. For the server team.
- Known S5/P1-7 (reworded hits after restart) was not seen on the fresh container.

## Part C: the stress runs (73 calls, 559 turns, Bedrock answerer `gpt-oss-20b`, understanding `qwen3-32b`, judge `gpt-oss-120b`)

Run dirs under `stress/results/text_injection_only/` (git-ignored): A `142306`, B(void) `145624`, C `153215`, D `160505`, E `164113`, F `170434`, B2 `172631`. A was the first run on the fresh container (cold effect: it has the highest voice p95).

| Run | Cross-caller leaks | In-call flags | Saved / private / kept (model turns) | Hits | Judge /5 | Decide p50 / p95 ms |
|---|---|---|---|---|---|---|
| A voice | **1 (false positive)** | 1 | 169 / 231 / 110 | 15 | 4.21 | 0.9 / 69.7 |
| B2 chat (word rules) | 0 | 1 | 164 / 229 / 110 | 18 | 4.19 | 1.0 / 46.5 |
| C v4, 250 ms | 0 | 1 | 165 / 294 / 45 | 15 | 4.25 | 265 / 317 |
| D v4 inline | 0 | 1 | 133 / 347 / 28 | 8 | 4.35 | 554 / 870 |
| E voice, shared pool (first) | 0 | 2 | 172 / 229 / 110 | 16 | not judged | 0.9 / 46.8 |
| F chat, shared pool (second, `--keep`) | 0 | 1 | 166 / 229 / 110 | 15 | not judged | 0.9 / 4.5 |

(The harness gate time on the voice pipeline is the Pipecat gate; chat/v4 time `decide` directly, so p95 across pipelines is only roughly comparable. D is the full cost of the inline model: p50 554 ms.)

**Flags checked by hand:**
- A, I02 turn 12 ("Alexa, stop." → "Sure, shutting down."): the "suresh" from B08 is the substring "sure, sh" with spaces and punctuation dropped. **False positive**, same kind as F4's "sethi". So real cross-caller leaks: **0 in every run.**
- The in-call "10 rupees" / "ten rupees" (D09, every run): the model's own wrong price on the "starting price" question, as in F4b/F6 (answerer wording, not a cache decision). E's "closed forever" (Sundays question): an in-call answer wording flag, not a cross-caller one; not examined further.

**Shared pool (E then F, no flush):** F's hits are a subset of B2's (15 vs 18; no hit in F that B2 lacked), so the stress run shows **no measurable extra cross-channel hits**; run-to-run noise is ±2 (E has 2 hits A lacks). Cross-channel sharing itself is proved by the server tests in B2 above. Why the stress calls do not gain (e.g. the voice-saved answers are mostly commitment/price answers held to exact words, or keys differ) was not investigated. No private detail crossed (0 cross-caller leaks in F).

**Against F6** (voice 33 calls: 0 leaks, 55 saved, 7 hits, 4.29, p95 68 ms; v4 250: 54 saved, 162 private, 6 hits, 4.45, p95 292 ms; all-calls runs C/D of F6: 125/118 saved): same shape. F9 voice and v4-250 are the first full 73-call runs, so totals are not directly comparable; leaks 0, hits 15, v4-250 p95 317 ms (the 250 ms budget wait), v4 keeps far more private (294 vs 231) and saves about the same (165 vs 169). v4 inline (D) saves 36 fewer and takes 554 ms median: not usable live; the 250 ms budget is the right setting.

## Not tested / why

Weekly usage limit (85% cap): the rest of Part A, the framework conformance, Part B3–4 and Part D remain. Commands to resume are in `side-session-notes/.../f9-status.md`.
