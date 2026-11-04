# P1: pre-merge tests A–G and the bugs they found (2026-11-04)

Before F5 (bringing `feat/v4` into `crowkis-sdk`), the owner asked for tests A–G. Owner decision during P1: **SDK bugs are fixed in P1 as they are found; server bugs are only logged.** Nothing is pushed.

## The tests

| Test | Files | What it covers |
|---|---|---|
| **A. Public API contract** | `fixtures/public-api.json`, `python/tests/test_public_api_snapshot.py`, `node/test-public-api.js` | **Python:** every name in `crowkis` (`__all__` plus public non-module attributes) and `crowkis.privacy`; each public class's members and every callable's parameter names. Members inherited from builtins are left out, because they vary with the Python version. **Node:** root `index.js` exports and class methods; `index.mjs` named exports; every `package.json` subpath's exports; the names each `.d.ts` declares. A name that's gone fails ("removed or renamed"), and so does a new one ("update the snapshot on purpose"). Regenerate with `CROWKIS_UPDATE_API_SNAPSHOT=1`; each language rewrites only its own section. |
| **B. Clean install** (`CROWKIS_SLOW_TESTS=1`) | `python/tests/test_install.py`, the last test in `node/test-packaging.js` | **Python:** builds the wheel and sdist from a copy, installs each into a fresh venv, and imports from a temp cwd (asserting `crowkis.__file__` is in the venv): every `__all__` name, `crowkis.privacy`, every module (integration modules may miss their framework), and `client/grpc/crowkis.proto`. Every `.py`/`.proto` in the wheel must also be in the sdist. **Node:** `npm pack`; every export target and every file reachable by relative `require` must be in the tarball; installs into a fresh project, then `require` and ESM `import` of the root and all 10 subpaths, and `tsc --strict` (node16) on a file importing each. Takes about 100 s (Python) and 17 s (Node). |
| **C. Old code still runs** | `v4-notes/old-suite-on-v4.md`, `v4-notes/old-suite-shim/` | The original repo's suite and examples on v4. As written, every old test fails at import (internal paths removed on purpose, P5.6/R1). Through an alias shim: Python 688 passed, 2 failed; Node 39/40. All failures are class (a) moved path or (b) an approved change (MT2). **No regressions.** |
| **D. Cross-channel leak** (real server, `CROWKIS_CONFORMANCE_SERVER=1`) | `python/tests/test_cross_channel_server.py`, `node/test-cross-channel-server.js` | Unique made-up words per run, tenant `voice`, both languages. Chat saves and voice asks, and the reverse: no private detail (name, phone, order id, stated fact) reaches the other channel's caller, any write, or a raw `cget_hit` probe in any segment. A general answer is **not** served across channels: by design, v4 P5 item 5 puts `kb=;channel=` in every segment. Controls show a general answer is served within a channel. In each channel, an answer repeating details the caller stated earlier is not saved and never reaches a second caller. |
| **E. Privacy fuzz** | `python/tests/test_privacy_fuzz.py`, `node/test-privacy-fuzz.js` | Fixed seeds, about 318 voice and 255 Chat cases per language (plus the weak-understander variants). **Details:** names (any case; 13 introduction phrasings), phones (7 digit formats and spelled out), emails, ids, addresses, dates of birth, Hinglish, Devanagari, a 3,000-character turn with a buried detail, blank turns. **Shapes:** the detail in the question; stated earlier and then repeated by the model. **Searched:** every write (keys, values, tool writes), raw and as digits only. **Controls:** 30 general questions per language must be saved, and every "stated earlier" category must save in at least 40% of the same calls without the detail, so no check runs over nothing. The Devanagari case instead asserts the call saves nothing at all (known limit L3/VD7). Chat runs with a good understander and with a weak one (a personal frame with no entities, or a general frame). |
| **F. Failure matrix** | `python/tests/test_failure_matrix.py`, `python/tests/test_failure_matrix_adapters.py`, `node/test-failure-matrix.js` | A real RESP stand-in on 127.0.0.1 that can be **down**, **hung**, **slow**, **refuse CSET**, have a **wrong token**, or return a **CSET error that quotes the question**. Run against `voice_session` (answer / decide+record / respond), `async_voice_session`, `Chat`, `CallSession` and `RealtimeGate`, and the Pipecat, LiveKit Py, Bolna and LiveKit JS adapters (in their venvs). **Every cell checks:** no exception, a defined outcome, the specific `stats()` counter (and the counters that must stay 0), and logs that hold neither the question nor the answer but do name an error class. |
| **G. Real-server conformance** | existing `test_conformance.py`, `test-conformance.js` | Run against `crowkis-demo` (tenant `voice`) in six configurations: system Python, Pipecat, LiveKit Py, Bolna, Node, Node + LiveKit JS. |

## Bugs found and fixed (SDK)

| ID | Severity | Found by | Bug | Fix |
|---|---|---|---|---|
| P1-1 | **High, privacy leak** | E | A name the caller stated earlier ("my name is Rahul Verma") was saved to the shared cache when a later general answer repeated it ("Refunds in 7 days, Rahul."). This was also on `feat/voice-adapters` (the original), in voice and in Chat with a weak understander. Phrasings it missed: "this is X calling", "X here", "myself X", "it's X", lowercase names, 3-word names, "Rahulji". | `08a24f7`, `5c6343d`, `b48d56f`: `_stated_names` / `statedNames` feed voice's `said_identifiers` (the `CallerIdentifier` rule) and Chat's `note_private` (the `PrivateWord` rule). |
| P1-2 | **High, privacy leak** | E | A phone number stated in words ("six seven zero eight …") and repeated by the answer was saved shared. Digits were caught. | `08a24f7`: `_spoken_numbers` turns runs of 4 or more spoken digits into a digit string on both sides of the identifier check. |
| P1-3 | **High, privacy leak** (from before v4) | review | Chat lost the caller's identifiers between turns (`CallState.to_dict` left them out), so a number stated earlier and read back later was saved shared when the understander missed it. | `9615f68`: `identifiers` are exported (hashed, like `private_words`) and restored. The exported dict gains a key; the two tests that pinned its absence were rewritten. |
| P1-4 (N1) | High | F | **Node client:** the AUTH reply had no timeout, so with a token set and a hung server every command hung for ever and late writes were never counted. | `655d906`: `_readWithin(timeoutMs)`. |
| P1-5 (F1, F2, V4-5) | Medium, privacy risk in logs | F | Refused saves, failed requests and audio-clip errors logged the error *message*. A server error that quotes the query put the caller's words into the app's log. | `beb8647`: every log line names the error type only. `decision.not_stored` still carries the text to the app. `test_voice_stress_bugs.py:424` asserted the old log text and now asserts its absence. |
| VD4 | Medium | open items | Follow-ups ("Can I pay it in two instalments?", "What were the fees again?") were answered without their context and shared. | `db96224` |
| T11 | Low (costs hits) | open items | "What is a PAN card used for?" was treated as cut off. | `db96224`: a wh-question of 4 or more words ending in a preposition and "?" counts as finished. |
| VD8 | Low (costs hits) | open items | "Hi there, quick question, what are your hours?" got no key. | `db96224`: voice strips a leading opener, but only when the rest is a question and not personal. |
| B4 | Test flake | open items | A 1 ns budget could read as 0 ms on Python 3.12. | `11a7244` |
| — | Test portability | the Pipecat venv run | The API snapshot pinned builtin exception methods, which differ by Python version. | `2bf332f` |

Server-side findings (logged, not fixed) are in `../sdk-docs/open-items.md`.

## Golden decisions changed (approved for these fixes)

Only `db96224` (VD4, T11, VD8) changed golden files: the voice files `phrases`, `stress-v1` and `stress-v2`, 19 turn entries. The Chat golden files are unchanged. Five turns go from private to stored shared:
- C09 #5 "What does your charity spend donations on?" (v1 and v2)
- F05 #6 "What is the difference between since and for?" (v1 and v2)
- K02 #2 "Hmm, how long does standard shipping, uh, take?" (v2)

None mentions the caller. Every changed decision, listed by rule and with before and after: [p1-golden-changes.md](p1-golden-changes.md). The other fixes left `fixtures/golden/` byte-identical.

## Review

One Opus review of the fixes and the tests: [p1-review.md](p1-review.md). Its must-fix items were all fixed:
- M1: name phrasings (`b48d56f`)
- M2: Chat identifiers (`9615f68`)
- M3/S1: vacuous fuzz cases (`d013881`)
- M4/S3: a skip left on a fixed bug, and loose log checks (`da05bad`)

It also strengthened D, which now has a "stated earlier, then repeated" case. Not done from the review: S4 (the snapshot pins parameter names, not defaults or keyword-only) and its notes.

## Results

Final runs, all at `ec0550a`. Each core suite ran twice.

| Suite | Result |
|---|---|
| Python (system 3.14) | 916 passed, 138 skipped, twice, apart from one flaky timing test (below) |
| Node `run-tests.js` | 68/68 files, twice |
| Pipecat 1.13 venv (whole Python suite) | 958 passed, 80 skipped |
| LiveKit Py 1.8.8 | 29 passed (livekit, conformance, failure matrix adapters) |
| Bolna | 127 passed |
| LiveKit JS 1.9.3 | 92/92 (livekit, conformance, failure matrix) |
| B, slow (`CROWKIS_SLOW_TESTS=1`) | Python 2 passed (~100 s); Node packaging 7 passed, 1 skipped (`tsc` not on `npx`, as before) |
| D, real server (`crowkis-demo`, tenant `voice`), at `da05bad` | Python 8 passed and Node 8/8, twice each |
| G, real server, at `da05bad` | **Earlier run, at `2085c23`:** all six configurations passed; LiveKit Py and Bolna each failed the Hinglish scenario once (the server was slow to make the new answer findable) and passed on rerun. **Final run:** "a reworded question hits" failed in all six. This is server issue S5 / X4: after the Docker restart, a raw `cget_hit` with no SDK involved returns nil for the stored pair. Every other scenario passed. |
| `fixtures/golden/` | Changed only in `db96224` (listed above). Byte-identical through every other commit. |

**Flaky timing test (from before P1):** `test_voice_review_fixes.py::test_review_11` gives a 22,500-word turn 0.5 s. That turn takes about 0.4 s alone, both at the commit before P1 (`9a663c5^`: 419 ms) and at HEAD. The time goes to `_sets_context` / `_tells_facts`, which P1 doesn't touch. In the larger full suite it sometimes takes 0.52 s and fails (about 1 run in 2). P1's name capture added 71 ms per such turn; `ec0550a` cut that to 15 ms. The test is not edited. Logged as P1-11.

Not covered: S4 from the review (the snapshot pins parameter names only, not defaults or keyword-only); real-server runs of E and F (they use stand-ins); Node fuzz cases are generated differently from Python's (same seed, different generator).
