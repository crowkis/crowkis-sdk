# F4: stress-run proof of v4 (2026-11-02)

**Verdict: v4 does not pass the gates. It is safe (0 real cross-caller leaks, correctness not lower) but it saves and hits
less than today's voice, because the model-read stated-facts rule (VD5) keeps most calls private. Do not merge on this
evidence; fix the F4 finding below first and re-run.**

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
| Decide p95 inside the 250 ms voice budget | 108 ms | 827 ms | 834 ms with the model inline; 49 ms without it | **FAIL as run** (model call p50 542 / p95 810 ms); the 250 ms budget would make the word rules read the turn. Not run with the budget on. |

Cache hits: voice 6, chat 4, v4 **1** (of 239 turns). Turn outcomes (model turns): voice private 123 / saved 53 / kept 52;
chat private 54 / saved 39 / kept 134; v4 private 188 / saved 41 / kept 5. Hard-pass: 99.2% / 97.5% / 98.7%.
Judge verdicts pass/warn/fail: voice 182/12/43, chat 190/6/42, v4 192/7/39.

### The v4 "leak" is a false positive
The checker flagged I01 turn 24 for "sethi" (H05's caller surname). The answer is "Because this claim involves damage to your own
vehicle, it will reduce your no-claim bonus for the year." Flattened without spaces, "becau**se thi**s" contains "sethi". No caller detail is in it.
The one in-call flag (D09, "10 rupees") is the same in all three pipelines: the answerer model's own wrong price.

## The earlier open items

- **VD5 (call-wide taint costs hits): still shows under v4.** 93 of 235 v4 model turns were decided by `VoiceStatedFacts` (private). Cause found
  with a probe (B08): after "my father passed away...", the classifier gets `facts=[]` and returns no `fact_relevance`, so the rule's default
  ("late, failed, unsure or silent: the fact counts") makes every later turn private, even "What documents do you need to close a deceased
  person's account?". The stated turn is not turned into a fact the model can judge. This is the main reason v4 saves less. A fix is SDK work, not done here.
- **VD8 (preamble gives no key): not improved.** Preamble turns ("Hmm, ...", "So, um, ..."): v4 5 private, 1 saved; voice 2 private, 1 hit, 1 saved, 2 kept. Too few turns to be firm.
- **VD4 (follow-up answered without context): not testable here.** A01a/I01a are not among the 33 Groq calls. Turns where the model saw "question + previous": voice 5, chat 12, v4 7.
- **V4-2 (wrong rewrite files an answer under the wrong question): not confirmed, not fully checked.** The first v4 run did not record the rewritten
  question. A re-run that records it (`asked`) stopped after 5 calls (Groq gpt-oss-20b daily limit): 11 answers saved, none under a question different from the caller's.
  Of v4's 41 saved answers, 6 were judged wrong, all made-up facts by the answerer (cyber-crime helpline number, bank holidays, discounts), none a rewrite mismatch.
  The remaining 28 calls need the re-run (`--pipeline v4 --resume` after the Groq limit resets; the first run's results are kept in `results/text_injection_only/v4-run1-results.json`).

## Not done / limits
- v4 with the 250 ms understanding budget on was not run (it measures the fallback, not the model).
- The Opus check of this analysis: see the end of this file.
- `crowkis-demo` stopped. Nothing pushed.
