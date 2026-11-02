# F4: stress-run proof of v4 (2026-11-02)

**Verdict: v4 does not pass the gates. It is safe (0 real cross-caller leaks, correctness not lower) but it saves and hits
less than today's voice (41 saved vs 53; 1 hit vs 6) and its model call is far outside the 250 ms voice budget. The loss to voice comes from
general questions read as personal (`OwnRecords`) and `PrivateChain`, not from VD5. Do not merge on this evidence; fix those and re-run.**

Cases: `text_injection_only_v2.json`, the 33 Groq calls (239 turns). Run dir (git-ignored):
`v4-notes/stress/results/text_injection_only/20261102-010159/` (`report.md`, `results.json`). Script: `v4-notes/stress/voice_stress_test.py`
(`--pipeline all` = voice, chat, v4; tenant `voice` flushed before each pipeline).

| Pipeline | What it is |
|---|---|
| voice | `voice_session` as today (word rules), through Pipecat `CrowkisLLM`, Groq gpt-oss-20b answers |
| chat | `CallSession` with an LLM understander (Bedrock `qwen.qwen3-32b`), no understanding budget |
| v4 | `voice_session(classifier=LLMClassifier, rewriter=LLMRewriter)`, same Bedrock qwen model, budget off, text only |

All three use the v4 SDK at `feat/v4` (default settings behave as today, golden files). Judge: Bedrock `openai.gpt-oss-120b`.
Bedrock cost: **0.41 USD** of the 2.00 cap (a partial v4 re-run is included).
Model change: earlier chat runs used Groq `qwen/qwen3.8-27b`; Groq's daily token limit stopped it, so chat was replayed on Bedrock qwen3-32b.

## Gates

| Gate | voice | chat | v4 | Result |
|---|---|---|---|---|
| 0 cross-caller leaks | 0 | 0 | 0 real (1 flagged, see below) | **PASS** |
| More saved answers than both | 53 | 39 | **41** | **FAIL** (beats chat by 2, loses to voice by 12) |
| Judge correctness not lower (mean 1-5) | 4.28 | 4.35 | 4.36 | **PASS** |
| Decide p95 inside the 250 ms voice budget | 108 ms | 827 ms | 834 ms with the model inline; 27 ms without it | **FAIL as run** (model call p50 551 / p95 829 ms); the 250 ms budget would make the word rules read the turn. Not run with the budget on. |

Cache hits: voice 6, chat 4, v4 **1** (of 239 turns). Turn outcomes (model turns): voice private 123 / saved 53 / kept 52;
chat private 54 / saved 39 / kept 134; v4 private 188 / saved 41 / kept 5. Hard-pass: 99.2% / 97.5% / 98.7%.
Judge verdicts pass/warn/fail: voice 182/12/43, chat 190/6/42, v4 192/7/39.

### The v4 "leak" is a false positive
The checker flagged I01 turn 24 for "sethi" (H05's caller surname). The answer is "Because this claim involves damage to your own
vehicle, it will reduce your no-claim bonus for the year." Flattened without spaces, "becau**se thi**s" contains "sethi". No caller detail is in it.
The one in-call flag (D09, "10 rupees") is the same in all three pipelines: the answerer model's own wrong price.

## The earlier open items

- **VD5 (call-wide taint costs hits): the mechanism is still there, but it is not what makes v4 save less than voice.** 93 of 235 v4 model turns
  (14 calls) were decided by `VoiceStatedFacts` (private). Cause (B08 probe, confirmed by the Opus code check): the classifier gets `facts=[]`
  and returns no `fact_relevance`, because `state.facts` is filled only from the model's memorable entities and the raw stated turns are never sent to it.
  The rule's default ("silent: the fact counts") then keeps every later turn private. On those same 93 turns voice saved 0 and chat saved 7, so VD5 costs
  v4 nothing against voice and at most 7 against chat. It is an SDK problem, not the stress harness.
- **Where v4 loses to voice (turn by turn):** 16 turns voice saved and v4 did not, 4 the other way (net -12). `OwnRecords` (general questions read as
  personal: "What is the UPI daily limit?", "Aur COD available hai?") 6, `PrivateChain` 5, `ConfidenceBar` 3, `DifferentQuestion` 1, a hit instead of a save 1.
- **VD8 (preamble gives no key): not improved.** Preamble turns ("Hmm, ...", "So, um, ..."): v4 5 private, 1 saved; voice 2 private, 1 hit, 1 saved, 2 kept. Too few turns to be firm.
- **VD4 (follow-up answered without context): not testable here.** A01a/I01a are not among the 33 Groq calls. Turns where the model saw "question + previous": voice 5, chat 12, v4 7.
- **V4-2 (wrong rewrite files an answer under the wrong question): not confirmed, not fully checked.** The first v4 run did not record the rewritten
  question. A re-run that records it (`asked`) stopped after 6 calls (Groq gpt-oss-20b daily limit): 11 answers saved, none under a question different from the caller's.
  Of v4's 41 saved answers, 6 were judged wrong, all made-up facts by the answerer (cyber-crime helpline number, bank holidays, discounts), none a rewrite mismatch.
  The remaining 28 calls need the re-run (`--pipeline v4 --resume` after the Groq limit resets; the first run's results are kept in `results/text_injection_only/v4-run1-results.json`).

## Not done / limits
- v4 with the 250 ms understanding budget on was not run (it measures the fallback, not the model).
- Opus check (done): leak, saved, hit, judge and p95 numbers confirmed; it corrected the 27 ms / 551 / 829 ms figures (first draft took them
  from the partial re-run) and the VD5 conclusion above. Caveats it raised: the saved-answers count is confounded by run order (saved + hits: voice 59,
  chat 43, v4 42, same result); the correctness gap (4.28 / 4.35 / 4.36) has no significance test and v4 sends 188 turns to the model with the whole call;
  the understanders differ (voice: word rules, chat and v4: Bedrock qwen3-32b); the run started 01:01 and was resumed at 11:01 and 11:40, and a resume does not flush the tenant
  (cache TTL 3600 s), so a resumed pipeline met a partly expired cache; chat had 3 hard "saved where it should not" fails, voice and v4 had none.
- The tenant `voice` was flushed before each pipeline, with the owner's OK for F4 only.
- `crowkis-demo` stopped. Nothing pushed.
