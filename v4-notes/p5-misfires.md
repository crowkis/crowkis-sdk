# P5 item 4: the misfires measured on 2026-10-22

From `crowkis-testing-scripts/demo/voice-agent/tests/voice_stress_results/text_injection_only/20261022-070930-partial/`
(Chat's rule checker on the voice stress cases). No understanding frames were recorded, so the tests use stand-in
frames. The voice outcomes are from `20261021-165200-partial`.

| # | Call, turn | Caller | Chat got | Voice got | Earlier turns |
|---|---|---|---|---|---|
| V5a | B05 t5 (Telecom) | "How long does porting take?" | kept, `V5_untagged_name` | saved | "I need a new SIM, I lost my phone." / "My number is 98450 12345." / "Can you activate the new SIM on this number right now?" / "What is the process to port my number to another network?" |
| V5b | B04 t7 (E-commerce) | "Can I get a refund to a different card?" | kept, `V5_identifying` | saved | "Where is my order?" / "The order number is six four two eight one five." / "It was a blue denim jacket I ordered last week." / "What is your return policy for jackets?" / "I want to return it." / "How long do refunds take to reach a UPI account?" |
| V6 | B03 t5 (Healthcare) | "Can I bring home food for a patient?" | kept, `V6_ungrounded:visitors` | saved | "I'm calling for my mother, Kamala Iyer." / "What time is her appointment tomorrow?" / "Her patient ID is 5521907." / "What are the visiting hours in the ICU?" (shared) |
| V7 | B05 t4 | "What is the process to port my number to another network?" | kept, `V7_lost:SIM` | saved | "I need a new SIM, I lost my phone." |
| flight | C01 t5 (Travel) | "Does the 8:45 PM flight have a meal?" | **saved as general** ("The 8:45 PM flight does not include a meal.") | kept | "I want to change my flight." / "The booking reference is K 7 B, no wait, K 7 D 9 2 X." / "Mumbai to Bangalore on the 14th." / "Move it to the 16th, evening." |

Other V7 hits on unrelated stated facts (voice kept these too): B09 "What is cognitive behavioural therapy?"
(`V7_lost:i want to book a session with my therapist`), B07 "How long do you keep call recordings under GDPR?"
(`V7_lost:all my data`), B08 "How long does the settlement of a deceased claim take?" (`V7_lost:my father passed
away last month ...`).

Notes: T21 in `sdk-docs/open-items.md`: voice's question-only answer to "porting" was about software porting, so a
share of V5a also needs the telecom context in the key. The flight answer is call-specific ("the 8:45 PM flight" is
this caller's itinerary) and was not grounded in any data.
