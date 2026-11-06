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

**Shared pool (E then F, no flush; re-run as E2/F2 with the same result):** F had no more hits than the chat run on an empty cache (15 vs 18), and of 181 F turns whose exact words E had saved only 7 hit. Traced: F did not flush; the tenant held E's entries (177 vectors); the same questions hit when run straight after (3-call set: 56% hits). **Cause: the server lowers a stored answer's hit confidence as it ages** (0.987 → 0.903 in 4 min, 0.81 in 8 min), and the SDK serves only above 0.92, so an answer older than about 3 minutes goes to the model. Entries are not lost (plain `cget_hit` still finds them; plain `cset` entries hit for 23 min). Hit rate by age: 56% at 0, 40% at 5 min, 12% at 10 min, 4% at 15 min. This is a server finding (F9-1 in `open-items.md`); not an SDK bug, harness fine. So the stress run cannot show cross-channel hits across a 20-minute gap; the real-server cross-channel tests (seconds apart) do show them. No private detail crossed (0 cross-caller leaks in F, F2).

**Against F6** (voice 33 calls: 0 leaks, 55 saved, 7 hits, 4.29, p95 68 ms; v4 250: 54 saved, 162 private, 6 hits, 4.45, p95 292 ms; all-calls runs C/D of F6: 125/118 saved): same shape. F9 voice and v4-250 are the first full 73-call runs, so totals are not directly comparable; leaks 0, hits 15, v4-250 p95 317 ms (the 250 ms budget wait), v4 keeps far more private (294 vs 231) and saves about the same (165 vs 169). v4 inline (D) saves 36 fewer and takes 554 ms median: not usable live; the 250 ms budget is the right setting.

## Not tested / why

Weekly usage limit (85% cap): the rest of Part A, the framework conformance, Part B3–4 and Part D remain. Commands to resume are in `side-session-notes/.../f9-status.md`.

## Update 2026-11-06: frameworks and repeated offline runs (real-server runs use `crowkis-f9`)

| Configuration | Result |
|---|---|
| Pipecat 1.12 (f6venv), real server: conformance + cross-channel | pass (9, 27 skipped) |
| LiveKit Python 1.8.8, real server: `test_livekit` + conformance | pass (23 passed, 18 skipped) |
| Node + LiveKit JS, real server: `test-livekit.js` + `test-conformance.js` | ran, no failures reported in the summary tail (not re-checked line by line) |
| Pipecat venv, full offline Python suite | 813 passed, 122 skipped |
| LiveKit Python offline | 23 passed, 30 skipped |
| LiveKit JS offline | 49 passed, 0 failed |
| System Python offline, 2nd run | 797 passed, 138 skipped (same as 1st) |
| `CROWKIS_SLOW_TESTS=1` Python (wheel/sdist install) | 799 passed, 136 skipped |
| Node offline, 2nd run (python3 shim on PATH) | 64/65 files (one failing file, not identified) |
| `CROWKIS_SLOW_TESTS=1` Node | 63/65 files (two failing files, not identified) |
| **Bolna** | **not run**: `bolna-venv2` has no pytest (`No module named pytest`); needs `pip install pytest pytest-asyncio` in that venv |

Still open: which Node files fail (the one in the offline run was `test-voice.js` in the first run), Bolna, Part B3–4, Part D.

## Update 2026-11-06 (later): Bolna, Node, B3, B4

**Fixed (SDK-side, test only):** `node/test-voice.js` "the node classifier agrees with the python classifier on all 44" failed on this Windows machine because `python3` is the Microsoft Store stub (exits 9009, not ENOENT), so the fallback to `python` never ran. It now falls back on any failure of `python3` (commit "test-voice: fall back to python…"). With it and `npm install` (typescript was missing), **Node: 65/65 files, also with `CROWKIS_SLOW_TESTS=1`** (the two slow failures were the missing `tsc` in `node_modules`, and the same test-voice file).

| Part | Result |
|---|---|
| Bolna (new Python 3.12 venv `bolna-f9`: bolna, pytest, pytest-asyncio, SDK editable; the old `bolna-venv2` had lost files) | offline 121 passed, 30 skipped; **real server** (`CROWKIS_CONFORMANCE_SERVER=1`, tests/test_bolna.py + test_conformance.py) 121 passed, 18 skipped |
| B3 server-marked tests (`test_voice_announce`, `test_voice_review_fixes`; Node `test-voice-announce`, `test-voice-rereview-fixes`) | Python 13 passed, 1 skipped; Node 7 passed, 1 skipped |
| B3 website snippet checks on the server (`check_voice_python.py`, `check_voice_node.js`) | **3/4 in both languages**: "a later caller is served from the cache" fails (see finding F9-2). `check_sdk_pages.py` / `.js` abort with `CSET rejected by security pipeline` |
| B3 examples (`python_custom_voice_loop.py`, `node_custom_voice_loop.js`) | run to the end; the loop prints the answer each call but the second call is not served from cache for the same reason. `python_langchain_cache.py` not run (no `langchain_core` in these venvs); `node_get_or_compute.js` ran |
| B4 failure cases on the real server (`v4-notes/f9/failure_cases.py`, `.js`) | **Python and Node: every call survived** (no exception reached the caller). Wrong token: turn goes to the model, `stored=False`, 13–23 ms. Server stopped (`docker stop`): turns go to the model in 2–3 ms, not stored. After `docker start`: a session that was already open loses its first write (no retries by design; 95–779 ms, later calls fine); a new session works at once. Server hung (`docker pause`): turn answered by the model after ~770 ms (the 250 ms budget + bounded write), write not stored, stats count it (`failed_writes`); after `unpause` all fine |

**To add to open-items** (the parent is cleaning that file; F9-1 above was already appended to it before I was asked to hold off — please keep or move it):
- **F9-1** (already in open-items.md): hit confidence decays with age.
- **F9-2 (server, High):** the write pipeline rejects short, ordinary answers: `CSET rejected by security pipeline (… the answer's overall score is too low, composite 0.73)` for "At nine.", "Refunds take five business days to reach your card.", and "Abrimos de 9 a 18 h, de lunes a sábado, y cerramos los domingos y festivos." (digits). Prose of 15+ words stores. A real agent's short answers ("At nine.") are never cached; the SDK reports `stored=False` / "the server refused the write", never an error to the caller. The website snippets and `fixtures/adapter-conformance.json` real-server scenarios used short answers and stopped passing on `dce94b4` (fixture fixed in 06e39f6; website pages in `sdk-docs/website/` not changed). Decide: server threshold, or make the pages' sample answers longer.
- **F9-3 (SDK/test env):** `python3` on Windows is a Store stub; `test-voice.js` now copes.
