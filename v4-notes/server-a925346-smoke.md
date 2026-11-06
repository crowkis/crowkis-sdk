# Server a925346 smoke test (2026-11-06)

**Server:** `crowkis:0.5.2-a925346` built from `D:\Tarkova\crowkis` (branch `crowkis/production-5.2`, 36 commits after `dce94b4`), container `crowkis-smoke` on 7393–7396, built-in judge (`judge=crowjudge match=ABSENT`), Community edition, token via `CROWKIS_AUTH_TOKEN`, tenants `voice` and `s12`. **SDK:** `feat/v4` at `30de111`. Container removed afterwards, image kept. Bedrock: 3.67 → 3.83 USD (answerer only, no judge).

## Smoke tests

| Test | Result |
|---|---|
| Real-server conformance, system Python | pass (1 test, 18 subtests; 27 skipped) |
| Real-server conformance + cross-channel, Node | pass (17 pass, 0 fail, 9 skipped) |
| Cross-channel server tests + `test_server_052_replies`, Python | pass (32 passed) |
| `failure_cases.py` / `.js` (wrong token, stop, restart, pause) | every call survived, no exception, in both languages. New: after `docker start`, the already-open session's first write now stores (Python 2c `stored=True`; before it lost it) |
| Website checks `check_voice_python.py` / `check_voice_node.js` | 3/4 in both: "a later caller is served from the cache" fails (S13, short sample answers) |
| Stress, voice (`--pipeline groq`, 7 calls, 54 turns incl. H01/H02, no judge) | 0 leaks in-call, 0 cross-caller, 100% hard pass, 3.7% hits |
| Stress, chat (same calls) | 0 leaks, 0 cross-caller, 100% hard pass; H01→H02 "How do I claim warranty" hit 0.99 across callers |

No SDK bugs. (The stress script crashes on a Windows console encoding error unless `PYTHONIOENCODING=utf-8` is set: harness only.) The stress script flushes the tenant it runs on, so the S12 probe ran on its own tenant `s12`.

## Server items

| Item | Status | Evidence |
|---|---|---|
| S12 / F9-1 | **Fixed** | Same words at 0/2/4/8 min: 0.9873 / 0.9870 / 0.9867 / 0.9862, all `serve` |
| S13 / F9-2 | **Still there** | "At nine." (composite 0.73) and the Spanish hours answer (0.74) refused with `-ERR`; "Refunds take five business days…" stores |
| MT3 | **Still there** | clinic address and "Dr. Meera Iyer and Dr. Arun Shah" answers: `cset` False / `NOTSTORED`; a parking answer stores |
| MT7 | **Not confirmed** | the normalized key is not visible from the SDK; exact repeat hits |
| VD1 | **Not exercisable** | no failing external judge in this setup |
| VD12 | **Still there** | 5 rephrasings (Saturday hours, password reset): all `infer`; the exact repeat serves |
| B3 | works | `not_stored` reads "the server accepted the answer and kept nothing (NOTSTORED)", no error; pipeline refusals stay `-ERR` and show as "server refused the write" |

Not run: Pipecat/LiveKit/Bolna conformance, full stress, judge.
