## Golden decisions changed by db96224 (vs db96224^)

Files changed: `fixtures/golden/voice/phrases.json`, `stress-v1.json`, `stress-v2.json`. No chat goldens, no `inputs.json` change. Compared turn by turn (call id + turn index), all fields except stats; plus the `writes` lists. Stats/writes changes follow from the turn changes and are not listed separately.

### Counts (turn entries changed)

| Fix | phrases | stress-v1 | stress-v2 | Total |
|---|---|---|---|---|
| VD4 (follow-up markers) | 2 | 1 | 1 | 4 |
| T11 (wh + preposition + "?" not CutOff) | 0 | 0 | 0 | 0 direct |
| T11 knock-on (CutOff -> later rule) | 1 | 3 | 3 | 7 |
| VD8 (opener stripped from key) | 2 | 2 (G04 #4, #5) | 4 (G04 #4, #5, K02 #1, #2) | 8 |
| Total | 5 | 6 | 8 | 19 |

G04 #5 is a knock-on of VD8 on G04 #4 (the earlier turn is part of the key). A04 #6 in v1 and v2 is VD4. Of the 19 entries, 3 (x2 files for two of them) go from not stored/private to stored shared: C09 #5, F05 #6 (v1 and v2) and K02 #2 (v2): 5 entries.

### Table

| Fix | File | Case / turn | Turn text | Field: before -> after |
|---|---|---|---|---|
| VD4 | phrases | "Can you say that again?" #0 | Can you say that again? | not_stored: "about this caller, no declared value..." -> "a follow-up with no earlier turn to key it on"; save_rule: PersonalTemplate -> NoKey (still not stored; rule unchanged) |
| VD4 | phrases | "Sorry, I didn't catch that, say that again." #0 | Sorry, I didn't catch that, say that again. | same as above: not_stored reason and save_rule PersonalTemplate -> NoKey (still not stored) |
| VD4 | stress-v1 | A04 #6 | What were the options again? | sees: 1 message -> 2 (prior turn now included, key = previous question + this one); rule ConfidenceBar, stored True unchanged |
| VD4 | stress-v2 | A04 #6 | What were the options again? | sees: 1 -> 2 messages ("What is the most expensive plan with international roaming?" + this); write key was "What were the options again?" -> "<prev> \|\| What were the options again?"; still stored |
| T11 knock-on | phrases | "What the hell is going on?" #0 | What the hell is going on? | rule: CutOff -> OwnRecords (still not stored); reason now "asked about their own records, no values to fill shared answer shape" |
| T11 knock-on | stress-v1 | E07 #6 | What name is the booking under? | rule: CutOff -> OwnRecords (still not stored/private) |
| T11 knock-on | stress-v2 | E07 #6 | What name is the booking under? | same: CutOff -> OwnRecords |
| T11 knock-on | stress-v1 | C09 #5 | What does your charity spend donations on? | rule CutOff -> ConfidenceBar; stored False -> True; not_stored "kept to this call..." -> none; cacheable False -> True; save_rule NotShareable -> None; sees null -> 1 message (the question) |
| T11 knock-on | stress-v2 | C09 #5 | What does your charity spend donations on? | same as v1; new write key "What does your charity spend donations on?" |
| T11 knock-on | stress-v1 | F05 #6 | What is the difference between since and for? | same change as C09 (CutOff -> ConfidenceBar, stored False -> True, sees null -> 1) |
| T11 knock-on | stress-v2 | F05 #6 | What is the difference between since and for? | same as v1 |
| VD8 | phrases | "Hello, how long does delivery take?" #0 | Hello, how long does delivery take? | sees/key: "Hello, how long does delivery take?" -> "how long does delivery take?"; stored key in writes changed likewise; stored unchanged |
| VD8 | phrases | "Okay, what is the refund policy?" #0 | Okay, what is the refund policy? | sees/key: "Okay, what is..." -> "what is the refund policy?" |
| VD8 | stress-v1 | G04 #4 | Okay, what does your product do? | sees/key: "Okay, what does..." -> "what does your product do?" |
| VD8 knock-on | stress-v1 | G04 #5 | What does it cost per month? | sees[0] "Okay, what does your product do?" -> "what does your product do?"; write key "Okay, ... \|\| What does it cost per month?" -> "what does your product do? \|\| What does it cost per month?" |
| VD8 | stress-v2 | G04 #4 | Okay, what does your product do? | same as v1 |
| VD8 knock-on | stress-v2 | G04 #5 | What does it cost per month? | same as v1 |
| VD8 | stress-v2 | K02 #1 | Um, uh, how long does standard shipping take? | sees/key: "Um, uh, how long..." -> "how long does standard shipping take?" (stored both ways) |
| VD8 | stress-v2 | K02 #2 | Hmm, how long does standard shipping, uh, take? | stored False -> True; not_stored "kept to this call..." -> none; cacheable False -> True; save_rule NotShareable -> None; sees null -> "how long does standard shipping, uh, take?"; rule stays ConfidenceBar |

### Not stored / private -> stored shared

All five are questions with nothing about the caller: no name, number, or "my ...".

| File | Turn | Text | Caller-specific content? |
|---|---|---|---|
| stress-v1 | C09 #5 | What does your charity spend donations on? | No. Generic question (it says "your", about the agent's org). |
| stress-v2 | C09 #5 | same | No |
| stress-v1 | F05 #6 | What is the difference between since and for? | No. English grammar question. |
| stress-v2 | F05 #6 | same | No |
| stress-v2 | K02 #2 | Hmm, how long does standard shipping, uh, take? | No. Generic shipping question; note the key keeps the mid-sentence "uh" and the stored answer is the model's reply to this wording. |

Caveats: C09 and F05 were previously held back only because the T11 CutOff misfire made them look unfinished and (per their old reason) dependent on earlier call content; now they pass as ordinary shareable turns, which depends on the earlier turns of those calls not having tainted the call (the golden shows ConfidenceBar, so no taint rule fired). The K02 #2 old not_stored reason was the generic "answer depends on what this caller said" though the rule was already ConfidenceBar; the cause is attributed to VD8 (opener "Hmm," no longer in key) from the diff only, I did not trace the code.
