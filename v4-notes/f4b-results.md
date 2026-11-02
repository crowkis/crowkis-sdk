# F4b: fixes for F4's two causes, then a re-run on a Bedrock answerer (2026-11-02)

**Verdict: v4 still does not pass the gates.** It is safe (0 cross-caller leaks in every F4b run). With the model inline it saves 43
answers against voice's 54. With the 250 ms budget on, it saves 55, but its decide p95 is 349 ms, and on every turn it is the word rules
reading the turn after a 250 ms wait. The remaining gap to voice is mostly `PrivateChain` (8 turns), which needs an owner decision (below).
Do not start F5 on this evidence.

## Part A: fixes (commit `38dc733`, nothing pushed)

1. **VD5: the classifier now sees the stated turns.** `VoiceReader` sends `state.facts` plus each stated turn, masked by
   `_unnamed` (`understanding/chat_details.py`, Node `unnamed`): the chat-reply masker (capitals, numbers, emails), plus any word a
   private turn of the call held. Opus review fix: `VoiceStatedFacts` still counts a stated turn whose masking hid a content word or
   a number (`_hidden`), because the model judged it without that word ("flying to _ with _ bags").
   - An existing test asserted the old design ("the model reads the call's facts, never its turns") and was replaced.
   - Another existing test still passes: a capitalised name ("Priya") never reaches the model.
2. **General questions misread as personal or as follow-ups.** The probe (Bedrock qwen3-32b, the in-call frames) showed:
   - the model marked products and topics as `identifying` ("UPI", "Sony WH-1000XM5", "iPhone 16"), so the reading was personal (`OwnRecords`);
   - it set `uses_state` when a stand-alone question named a topic already in the call's facts, so the turn was a follow-up (`PrivateChain`).

   The fix is two prompt lines (Python and Node `INSTRUCTIONS`):
   - identifying only points to a person (where the caller lives is an address);
   - naming a topic of the call is not `uses_state`.

   No code floor changed.
- Tests failing first, then passing, in Python and Node, with "must still be private" controls: a relevant stated turn, an allergy the
  model calls irrelevant, and a stated place or number the model never saw.
- Suites run twice: Python 827, Node 62/62. Frameworks: Pipecat 32, LiveKit Py 23, LiveKit JS 49, Bolna 121. `fixtures/golden` unchanged.
- Opus review: no blockers. It found the medium point (fixed, above) and two low wording points (applied).
- Left as limits: a lowercase surname or spoken digits in a stated turn reach the model when a private turn did not already hold them
  (the docstring now says to plug in the app's own model). VD5 stays unfixed for non-Latin stated turns, which are masked whole and so stay private.

## Part B: re-run

Cases `text_injection_only_v2.json`, 33 calls / 239 turns. Answerer: Bedrock `openai.gpt-oss-20b` for every pipeline. The voice pipeline's
Groq service is swapped in-process for the same OpenAI-compatible service on Bedrock, with each answer's tokens added to the spend file.
Understanding: `qwen.qwen3-32b`. Judge: `openai.gpt-oss-120b`. Nothing on Groq, apart from the server's own decide engine
(`crowkis-demo` config, not changed). Each run started from a fresh flush of tenant `voice` (each log prints "emptied tenant 'voice'"; results.json does not record it). Run dirs (git-ignored) are under
`v4-notes/stress/results/text_injection_only/`:

| Run | Dir | What |
|---|---|---|
| 1 | `20261102-122010-partial` | v4, model inline, budget off, `asked` recorded |
| 2 | `20261102-122614-partial` | v4, `--understand-budget-ms 250` |
| 3 | `20261102-123205-partial` | voice (`voice_session`, Pipecat), Bedrock answerer |
| chat | `20261102-010159` (F4) | not re-run, 39 saved |

`20261102-123058-partial` is a voice start stopped after one call (the spend-file race below); ignore it.

### Gates

| Gate | voice (3) | chat (F4) | v4 inline (1) | v4 250 ms (2) | Result |
|---|---|---|---|---|---|
| 0 cross-caller leaks | 0 | 0 | 0 | 0 | **PASS** |
| Saves more than voice and chat | 54 | 39 | **43** | 55 | **FAIL** inline; run 2 beats voice by 1, as word rules plus a wait |
| Judge correctness not lower (mean /5) | 4.49 | 4.35 | 4.40 | 4.43 | **Inconclusive**: -0.09 / -0.06 with no significance test. Voice moved +0.21 from F4 (4.28) by swapping the answerer alone. Judge fails: voice 41, v4 33 / 28 |
| Decide p95 ≤ 250 ms (run 2) | 12 ms | — | 935 ms | **349 ms** (p50 268) | **FAIL** (nearest-rank p95; report.md interpolates 923 / 347) |

- **Cache hits:** voice 5, v4 4 / 4 (F4: v4 1, chat 4, voice 6).
- **Hard pass:** 99.6% / 99.2% / 99.2%.
- **Model-turn outcomes:**
  - run 1: private 177, saved 43, kept 11;
  - run 2: private 161, saved 55, kept 15;
  - voice: private 123, saved 54, kept 52.
- **The one in-call flag** (D09 "10 rupees") is the answerer's own wrong price, the same as in F4. B09's fail is a missing helpline in the
  answer (`must`), the answerer's wording, not a cache decision.

**Run 2 is not a v4 measurement.** All 239 turns took at least 250 ms, fillers included. The model (run 1 understanding: p50 584 ms, range 285–1613 ms) never answered inside the budget, so the
word rules read every turn after a fixed 250 ms wait. The rule's budget is spent before the cache lookup starts, so p95 ≤ 250 ms cannot
hold while the budget is 250 ms.

## The items asked for

- **VD5.** `VoiceStatedFacts` decided 90 model turns, against 93 in F4:
  - 25 are the stated turns themselves;
  - 65 are later turns.

  The model now sees the stated turns and mostly judges them as changing the answer (bereavement B08, emergency D04, flight change C01),
  which keeps those turns private, as the rule intends. **Voice saved none of those 65 turns either**, so VD5 costs v4 nothing against voice.
  The mechanism is fixed; the cost was never the gap.
- **The F4 OwnRecords / PrivateChain turns.** Fixed: "What is the UPI daily limit?" (H03), "Aur COD available hai?" (F01) and "iPhone 16
  price" (H08) are no longer the reason v4 loses. Turns voice saved or hit and v4 (run 1) did not: 14. v4 saved 2 that voice did not.
  - **PrivateChain 8:**
    - B02 "How long does claim settlement usually take?" and "What documents are needed for a reimbursement claim?"
    - B06 "What happens if I enter the wrong PIN three times?"
    - D01 "What discount codes are available?"
    - E03 "What payment methods do you accept for electricity bills?"
    - E08 "How do I update my KYC?"
    - H01 "How do I claim warranty for headphones?"
    - H04 "What's the UPI transaction limit per day?"

    qwen still sets `uses_state` when the call's facts hold the same topic (the prompt line did not stop it; probe: H04, B02, H01), and the
    chain before it is private, so `PrivateChain` keeps the turn.
  - **OwnRecords 4:** B04 "Can I get a refund to a different card?", H07 "What is the refund timeline for card payments?" (misreads),
    and B06 "Can you skip the verification this once?", B07 "What personal data does HR hold about me?" (rightly private).
  - **ConfidenceBar 2:** B01 and B04 (hit confidence below the 0.92 spoken bar).
- **VD8 (preamble).** K02's four preamble turns: v4 saved 3, kept 1; voice saved 2, kept 2. Slightly better, but too few turns to be firm.
- **V4-2 (all 33 calls).** 46 shareable model turns: 37 saw the question alone, 9 saw "question + previous". **None** was filed under a
  question worded differently from the caller's: no accepted rewrite became a cache key in this run. Not confirmed.
- **Spend.** The spend file records $0.96 of the $2.00 cap, so this re-run cost about $0.55. That covers the probes (about $0.05), run 1 (about $0.16), run 2 (about $0.15, reconstructed), run 3 (about $0.03) and three judge passes (about $0.13). The exact split is uncertain: an earlier counter reset left the pre-run baseline unsure, and rounding up to $0.80 added about $0.02.
  - **The figure is reconstructed.** During run 2, the budgeted understanding thread and the answer call wrote the spend file at the same time, and it reset twice.
  - The total was rebuilt from the per-call headers in the log, rounded up to $0.80 before run 3.
  - The script now writes the file under a lock with an atomic replace, checked with 4 threads × 200 writes.
  - Earlier, one test call also reset the counter (the file was opened for writing before it was read); that was fixed the same way.

## Caveats (Opus check of this analysis: every number confirmed; these are the confounds)
- **Run 2 beats voice only because the word rules are looser than the model.**
  - Under the word rules, `PrivateChain` falls from 10 turns to 2, and `OwnRecords` from 80 to 64.
  - That difference is the gap to voice, not something v4 adds.
- **The chat column is not comparable.**
  - F4's chat run used a Groq answerer and shared tenant `voice` with the other two pipelines.
  - It also has 4 "refused" outcomes that the other runs lack.
- **The latency gate compares different work.** Voice's decide is a lookup only; v4's decide includes understanding.
- **The answer path differs.** Voice answers through Pipecat streaming, v4 without streaming. That can change the answer text, and with it the saved, kept and judge results.
- **One run per arm, no repeats.** Run order was v4, v4 250 ms, then voice, all within 12 minutes (cache TTL 3600 s, each run flushed first). Small gaps (K02 3 vs 2, a save margin of 1) are within run-to-run noise.

## Decision needed (owner)

The `PrivateChain` turns are the remaining gap with the model inline. The prompt does not stop qwen setting `uses_state` for a
stand-alone question whose topic is in the call's facts. Closing it in code would mean counting a model "follow-up" reading less
(for example, ignoring `uses_state` when the frame's stand-alone question carries the turn's own words). That loosens a privacy rule,
so it was not done. The latency gate needs either a faster understander or a different budget design (understanding in parallel
with the lookup); neither was in scope.
