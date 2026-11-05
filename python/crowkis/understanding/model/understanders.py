"""Turn understanding: one slot that turns a caller's sentence into a TurnFrame
(turn understanding v2.2, part 3).

Anything that implements ``understand(turn, state) -> TurnFrame`` plugs in: the server's
model once CTURN exists, a local Rust model, or the interim LLM adapter below. Whatever
plugs in, the word rules still decide what is shared, so a weak model costs cache hits,
never privacy.

  LLMUnderstander     interim: asks the app's own LLM provider for the frame. Works end to
                      end, but adds one model call per turn (fine for chat and demos, too
                      slow for production voice).
  WithFallback        tries one understander, falls back to another on any failure."""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional, Protocol, Sequence

from ...state.call_state import CallState
from ..slots import Reading
from .frame import TurnFrame, FrameReading

Message = Dict[str, str]


class Understander(Protocol):
    def understand(self, turn: str, state: CallState) -> TurnFrame: ...


def _uncertain(reason: str = "") -> TurnFrame:
    """The fail-closed frame: never shared, handled by the agent."""
    return TurnFrame.from_dict({"kind": "unclear", "confidence": 0.0, "abstain": True, "note": reason})


class WithFallback:
    """Use ``primary``; if it raises or returns nothing usable, use ``fallback``."""

    def __init__(self, primary: Understander, fallback: Understander) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_failures = 0

    def understand(self, turn: str, state: CallState) -> TurnFrame:
        try:
            frame = self.primary.understand(turn, state)
        except Exception:  # noqa: BLE001 - a broken understander must never end a call
            frame = None
        if frame is None or (frame.kind == "unclear" and frame.confidence == 0.0):
            self.primary_failures += 1
            return self.fallback.understand(turn, state)
        return frame


INSTRUCTIONS = """You are a turn-understanding model for a customer-support agent. You do not answer the caller.
You describe the caller's latest turn as one JSON object, using only: the turn, the agent's last reply, and the
call state (what was established earlier). Never invent facts the caller or agent did not say.

Return exactly:
{"kind": "general|personal|live|action|dialogue|chitchat|sensitive|unclear",
 "urgent": true|false, "subject": "none|self|other", "task_step": true|false,
 "confidence": 0.0-1.0, "abstain": true|false,
 "entities": [{"text": "...", "type": "...", "identifying": true|false, "answer_relevant": true|false}],
 "attributes": {"segment": {"value": "...", "changes_answer": true|false},
                "region": {"value": "...", "normalised": "...", "changes_answer": true|false}},
 "uses_state": true|false,
 "question": "standalone question, or -",
 "question_type": "policy|how_to|product_fact|place_fact|search|other",
 "language": "language code the reply must be in, e.g. en, hi, ta",
 "fact_relevance": [{"fact": "...", "type": "allergy|medication|pregnancy|age|diet|condition|trip|budget|other",
                     "changes_answer": true|false}]}

kind: general = the same answer for every caller from the business's own knowledge (policies, how-to,
troubleshooting, product facts, stable facts about a named place, searches with stable criteria). personal = about
this caller or another specific person (their records, purchases, account, eligibility, identity, details they
give). live = fast-changing data (stock, outages, open now, availability for a date, changing prices). action = asks
the agent to do or change something. dialogue = only meaningful against the previous turn (answers to the agent's
question, confirmations, corrections, choosing, repeats, complaints, steering). chitchat = greetings, thanks,
goodbyes. sensitive = medical, legal, financial or safety advice; emergencies. unclear = garbled or out of scope.
With two substantive parts: action > personal > live > sensitive > dialogue > unclear > chitchat > general.
Greetings, thanks and self-introductions attached to a question are noise.
urgent: an emergency or crisis that needs immediate help.
task_step: the turn gives details for a task the agent is running (booking, ordering, account change), such as
dates, party size, budget or preferences in reply to the agent's question.
entities types: person_name, id_number, contact, address, payment, date_of_birth (identifying); owned_record,
own_purchase, other_person, place, tier, product, plan_product, quantity, time, condition, topic.
List every capitalised word, name or acronym of the turn as an entity with its type (a person's name is
person_name; CSV or SSO is topic; PayPal or MacBook is product).
A person's name is person_name however it is written (all capitals or lowercase); a word that acts like a
person ("Can McKenzie return items?") or that something is for ("returns for PRIYA") is a person, never a
product or place.
identifying: true only for what points to one person (a name, an ID, a contact, an address, a payment detail, a
birth date, an order or account number; where the caller lives is an address); a product, a topic, a place the
question is about, a plan or a condition is never identifying.
attributes: tier and location from the turn or the call state; changes_answer only if it changes the answer.
A location is where the user is (their city or country), never a place the question is about.
A segment is the customer's tier or plan (e.g. premium), never the topic of the question.
uses_state / abstain: resolve "it", "that", "the other place", ellipsis from the call state, the agent's mentions
and last reply. If the referent is not there, abstain = true and kind = dialogue. Never guess.
uses_state is false for a stand-alone question that only names a topic also in the call state.
question: only for general. Standalone and de-identified, built only from words in the turn, the agent's last reply
and the call state. Keep every product, place, condition, quantity, time and negation; drop names, IDs, contacts.
One sentence ending in "?", at most 25 words, generic voice ("How do I reset a password?").
language: the language the caller asked replies to be in (now, or earlier: call_state.language), otherwise the
language of the turn. Write the question in English whatever the turn's language; the reply language is separate.
question must also carry every fact in call_state.facts that changes the answer (an allergy, an age, a diet, a
trip) in generic words ("for someone with a peanut allergy", "for a 3-year-old").
How-to questions phrased with "my" ("How do I export my data?", "How do I reset my password?") are general with
subject none: the steps are the same for everyone. A question whose answer depends only on facts the caller told
(an allergy, an age, a diet, a trip, a budget) is general: put those facts in the question; personal is only for the
caller's own records, account, orders, bookings or identity.
If the turn asks for the same thing as call_state.active_question ("what were the steps again?"), return that
question exactly as it is written there. Facts about someone the caller mentions ("my mother has type 2 diabetes")
also make a later question general: "What foods should someone with type 2 diabetes avoid?".
fact_relevance: one entry for each fact in call_state.facts and each fact this turn states, "fact" written exactly
as given there. changes_answer is true if the answer to this turn could differ for someone with that fact (an allergy
and a dessert question, an age and a dose); false only when the answer is the same for everyone (a car accident and
"what is a deductible?"). When unsure, true.
confidence: your calibrated probability that kind and question are right."""


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


class LLMUnderstander:
    """Interim understander backed by the app's own LLM.

    ``complete`` takes chat messages and returns the model's text (any provider).
    ``business`` describes the business in a few sentences: what it sells, what counts as
    policy, what tasks the agent runs. The call state crosses to the provider, never the
    caller's identity.
    """

    def __init__(self, complete: Callable[[List[Message]], str], *, business: str = "") -> None:
        self.complete = complete
        self.business = business.strip()

    def messages(self, turn: str, state: CallState) -> List[Message]:
        system = INSTRUCTIONS + ("\n\nBUSINESS:\n" + self.business if self.business else "")
        payload = {"call_state": state.snapshot(), "turn": turn}
        return [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]

    def understand(self, turn: str, state: CallState) -> TurnFrame:
        data = _extract_json(self.complete(self.messages(turn, state)))
        if data is None:
            return _uncertain("model output was not a JSON object")
        return TurnFrame.from_dict(data)


class LLMClassifier:
    """Adapter: reads a voice turn through an ``Understander`` (``LLMUnderstander`` over the app's
    ``complete`` function, or any other). The model sees the turn, the call's facts (what earlier
    frames remembered) and the turns in which the caller told it something (the same model already read
    them as they were said), so it can say which of them change this answer. The stated turns are masked (capitals, numbers,
    emails), not anonymised: plug in the app's own model, the one that already hears the call."""

    def __init__(self, understander: Understander) -> None:
        self._understander = understander

    def classify(self, text: str, facts: Sequence[str] = ()) -> FrameReading:
        """The model's reading of the turn."""
        return FrameReading(self._understander.understand(text, CallState(facts=list(facts))))


class LLMRewriter:
    """Adapter: keys a shareable turn on the understander's stand-alone, de-identified question. When
    the classifier's reading already carries the model's frame (``LLMClassifier`` over the same
    understander), that frame is reused and the model is asked once per turn."""

    def __init__(self, understander: Understander) -> None:
        self._understander = understander

    def rewrite(self, text: str, reading: Reading) -> Optional[str]:
        """The model's question for a turn that may be shared, else None (the caller's words)."""
        if reading.is_personal:
            return None
        if not isinstance(reading, FrameReading):
            reading = FrameReading(self._understander.understand(text, CallState()))
        return reading.question


