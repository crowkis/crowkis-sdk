# F6: the stress test on the newest server (2026-11-05)

**Server:** `crowkis:0.5.2-dce94b4` (container `crowkis-f6`, fresh data, ports 7383-7386, Community edition), against F4b's `6ecdb9b` (`crowkis-demo`).
**SDK:** `feat/v4` at `7028548` (editable install in a new Python 3.12 venv; Pipecat 1.12.0). Answerer Bedrock `openai.gpt-oss-20b`, understanding `qwen.qwen3-32b`, judge `openai.gpt-oss-120b`, as in F4b. Cases `text_injection_only_v2.json` (73 calls / 559 turns).
**Bedrock spend:** 0.96 USD before F6, **1.59 USD after** (cap 2.00, script stop 1.90, never raised). Tenant `voice` flushed at the start of each run (on `crowkis-f6` only).

## Scope: why the runs are 33 + 40 calls

The script plays a call on the voice (`groq`) and `v4` pipelines only if the case has `"groq": true`: 33 of the 73 (the curated Groq subset F4/F4b used). The other 40 are Gemini-only. The owner asked for both, so:
- **Part 1** (33 calls, 239 turns): the F4b-comparable runs, A and B.
- **Part 2** (40 calls, 320 turns): the 40 `groq: false` calls, played with a new `--all-calls` flag (default behaviour unchanged), runs C and D. No call needed anything the Groq/Bedrock path lacks, so none was skipped.
- Run (c), v4 with no budget (inline), was **not run**: 1.59 USD spent left no clear room under 1.90.

| Run | Pipeline | Calls | Dir (git-ignored, under `stress/results/text_injection_only/`) |
|---|---|---|---|
| A | voice | 33 | `20261104-234849-partial` |
| B | v4, `--understand-budget-ms 250` | 33 | `20261105-000317-partial` |
| C | voice, `--all-calls` | 40 | `20261105-015317-partial` |
| D | v4 250 ms, `--all-calls` | 40 | `20261105-021322-partial` |

(`20261104-234752-partial` is the 2-call smoke run; ignore it.)

## Part 1: 33 calls, against F4b

| | F4b voice | **F6 A voice** | F4b v4 250 | **F6 B v4 250** |
|---|---|---|---|---|
| Cross-caller leaks | 0 | **0** | 0 | **0** |
| In-call flags | 1 | 1 | 1 | 1 |
| Hard pass | 99.6% | 99.2% | 99.2% | 99.2% |
| Saved (model turns) | 54 | **55** | 55 | **54** |
| Private / kept | 123 / 52 | 123 / 51 | 161 / 15 | **162 / 14** |
| Cache hits | 5 | 7 | 4 | 6 |
| Judge correct (/5) | 4.49 | 4.29 | 4.43 | **4.45** |
| Judge fails (turns) | 41 | 43 | 28 | 30 |
| Decide p50 / p95 (nearest-rank) | ~1 / 12 ms | 0.8 / 68 ms | 268 / 349 ms | **264 / 292 ms** |

- Same shape as F4b: v4 with the 250 ms budget saves 54 against voice's 55 (F4b: 55 against 54), so the **save gap is still zero, and not a win**. v4 keeps 162 turns private against voice's 123, and 14 against 51 kept.
- **p95 is 292 ms**, above the 250 ms gate, again because every turn waits the 250 ms budget before the word rules run (p50 264 ms). It is lower than F4b's 349 ms. Voice's p95 here is 68 ms, higher than F4b's 12 ms (new server container; not investigated).
- Judge correctness: A is 0.20 lower than F4b's voice and B equal to F4b's v4. The answerer is the same model; judge scores move between runs, as F4b already saw (+0.21 from changing the answerer alone). v4 is +0.16 above voice here (F4b: -0.06); no significance test.
- **The in-call flags are the same two as in F4b**, answerer wording, not cache decisions: D09 "10 rupees" (the model's own wrong price), B09 (no helpline in the answer).

## Part 2: the 40 extra calls (A01-A09, C03-C09, D02/05/07, E01/02/04-07, F02/03/05/06, G01-G06, I02, J01-J04)

| | **C voice** | **D v4 250 ms** |
|---|---|---|
| Cross-caller leaks | **0** | **0** |
| In-call flags | 0 | 0 |
| Hard fails / hard pass | 10 / 96.9% | 10 / 96.9% |
| Model turns saved | 125 | 118 |
| Private / kept | 105 / 58 | 134 / 31 |
| non_answer / not_saved / interrupted | 4 / 9 / 0 | 5 / 10 / 3 |
| Cache hits | 7 | 7 |
| Judge correct (/5) | 4.21 | 4.02 |
| Judge fails (turns) | 58 | 72 |
| Decide p50 / p95 | 3.6 / 118.5 ms | 267 / 321 ms |

- v4 saves 7 fewer than voice (118 against 125) and judges 0.19 lower with 14 more failed turns, almost all in cause `model` (81 against 61): the answer wording from the non-streaming answerer, not a cache decision (judge cause `cache`: 2 against 1). 3 v4 turns were `interrupted`.
- **The 10 hard fails are nearly the same list in both pipelines:**
  - 9 are `sees`: "model saw question, expected question + previous" (see F6-1).
  - G05 ("I fell in the bathroom") has no emergency or help in the answer (`must`, the answerer).
  - Voice also fails G01 ("Yes, who is this?" saved: "I am ChatGPT...") and I02 ("Add milk and eggs to my shopping list" saved); v4 fails G01 only (it kept I02 t3).

## Leaks

No cross-caller leak in any of the four runs (checker: `leaks_cross_caller` 0 in A, B, C, D), so there was no flagged case to check by hand. The one in-call flag (D09) is the answerer's wrong price, the same as F4/F4b: private to its own call.

## Findings (logged in `sdk-docs/open-items.md`)

- **F6-1:** a follow-up that only makes sense with the earlier turn ("Compare it with the MacBook Air", "Do I need an ID proof for that?", "Done, what next?", "How many times do you try again after that?") is sent to the model as the question alone and the answer is **saved shared**, on both voice and v4 (A05 t7, A09 t8, C05 t4, C08 t4 in both; C03 t7 voice only). A later caller who says the same words would get an answer to a question that has no antecedent. This is a wrong-answer risk, not a private-data leak; this run produced no hit in another call from it.
- **F6-2:** "Yes, who is this?" is saved shared with "I am ChatGPT, a virtual assistant trained by OpenAI" (both pipelines): the answerer's identity answer, cached for every caller.
- **F6-3:** voice saves an action request ("Add milk and eggs to my shopping list", I02 t3) as a shared answer; v4 kept it.
- No server bug found. Server startup line: `judge=crowjudge match=ABSENT (near-miss questions verified by relevance only)` (not compared with `crowkis-demo`'s).

## Verdict

Same as F4b: **v4 is safe (0 cross-caller leaks in all four runs) but does not save more than voice**: -1 on the 33 calls, -7 on the 40, and p95 292-321 ms with the 250 ms budget (gate: 250 ms). The newest server did not change this. The new finding is F6-1, which holds for voice too.
