# F7: golden changes (owner-approved for these fixes only)

Three files changed (voice): `phrases.json`, `stress-v1.json`, `stress-v2.json`. Chat goldens and the voice `conformance.json` / `hit-guards.json` are identical. The `sees` field also changes on the follow-up turns below: they now read the whole call (private) instead of the question alone. Decisions that stay not-stored or private are listed too, because their rule changed.

| Call / turn | Fix | Rule, before → after | Stored, before → after |
|---|---|---|---|
| stress A05 t6 "How many times do you try again after that?" | F6-1a | sees: question alone → whole call | unchanged |
| stress A09 t7 "Do I need an ID proof for that?" | F6-1a | sees: question alone → whole call | unchanged in the flag; the answer is now saved under "previous turn + follow-up" instead of as the bare follow-up's own shared key (the bare key was a leak) |
| stress C03 t6 "Compare it with the MacBook Air." | F6-1b | sees: question alone → whole call | unchanged |
| stress C03 t7 "Which is cheaper?" (after the above) | F6-1b knock-on | ConfidenceBar → FollowUpWithoutContext, save NoKey | saved → not saved |
| stress C05 t3 "Done, what next?" | F6-1c | ConfidenceBar → PrivateChain, save NonAnswer (v1) / none (v2) → NotShareable | saved (v2) → not saved |
| stress G01 t1 "Yes, who is this?" | F6-2 | ConfidenceBar → PrivateChain, save none → NotShareable | saved → not saved |
| stress I02 t2 "Add milk and eggs to my shopping list." | F6-3 | save none → VoiceActionClaim | saved → not saved |
| phrases "Can I sue you for this?", "How much will I pay for this?" | F6-1a | save PersonalTemplate → NoKey (single turn, no earlier turn) | not saved → not saved |
| phrases "Yes, that's right.", "No, that's wrong.", "No, I meant the blue one." | F6-2 | save PersonalTemplate → NoKey | not saved → not saved |

(The same rows appear in both stress files, except I02: it changed only in `stress-v1`; in `stress-v2` the stub answer is "Here is the answer.", which no answer-side rule can catch. Matching `stats.rules` counters change too, and `uncacheable_personal` goes 1 → 0 for four of the `phrases` calls whose save reason became NoKey.) A turn that opens with "Yes," / "No," and then asks a question of its own ("Yes, what are your opening hours?") stays shareable: the opener is a follow-up only when the rest is itself a follow-up or asks nothing. Nothing here keeps a general question newly private: every changed turn is a follow-up or answers the bot's own question. "Can I sue you for this?" and "How much will I pay for this?" were already private; only the reason changed.

Also changed: `_ACTION_CLAIM` now matches "I will / I'll" + add, cancel, book, send, schedule, reserve, place, remind, order, so a promise ("I will add milk...") is kept private on voice and chat alike. No chat golden changed.

Known gap (review): an action request is only caught by the answer's wording. "Add milk and eggs to my shopping list" with an answer like "Done! Milk and eggs are on your list." is still saved shared; a request-side rule is logged in `sdk-docs/open-items.md`.
