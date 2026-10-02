"""Turn understanding: one slot that turns a caller's sentence into a TurnFrame
(turn understanding v2.2, part 3).

Anything that implements ``understand(turn, state) -> TurnFrame`` plugs in: the server's
model once CTURN exists, a local Rust model, or the interim LLM adapter below. Whatever
plugs in, the rule checker still decides what is shared, so a weak model costs cache hits,
never privacy.

  ReplayUnderstander  safe fallback with no model: only exact repeats of questions that
                      were already verified are recognised; everything else is not shared.
  LLMUnderstander     interim: asks the app's own LLM provider for the frame. Works end to
                      end, but adds one model call per turn (fine for chat and demos, too
                      slow for production voice).
  WithFallback        tries one understander, falls back to another on any failure.
"""

from __future__ import annotations

import json
import re
import string
from typing import Callable, Dict, List, Optional, Protocol

from .callstate import CallState
from .turn import TurnFrame

Message = Dict[str, str]


class Understander(Protocol):
    def understand(self, turn: str, state: CallState) -> TurnFrame: ...


def _uncertain(reason: str = "") -> TurnFrame:
    """The fail-closed frame: never shared, handled by the agent."""
    return TurnFrame.from_dict({"kind": "unclear", "confidence": 0.0, "abstain": True, "note": reason})


_PUNCT = re.compile("[" + re.escape(string.punctuation.replace("'", "")) + "]")


def _normalise(text: str) -> str:
    """Case, punctuation and spacing never make two wordings different; words always do."""
    return " ".join(_PUNCT.sub(" ", (text or "").lower()).split())


class ReplayUnderstander:
    """Recognises only exact repeats of already-verified questions.

    Seed it with the questions the business already answers (``known``), and let the session
    ``remember`` every question the rule checker verified. With no model loaded this is the
    only thing allowed to share: it can miss, but it cannot be talked into a leak, because
    a repeat of a verified standalone question is the verified question.
    """

    def __init__(self, known: Optional[Dict[str, str]] = None) -> None:
        # normalised wording -> (verified question, question_type)
        self._known: Dict[str, tuple] = {}
        for question, qtype in (known or {}).items():
            self.remember(question, question, qtype)

    def remember(self, turn: str, question: str, question_type: str = "other") -> None:
        for wording in (turn, question):
            key = _normalise(wording)
            if key:
                self._known[key] = (question, question_type)

    def understand(self, turn: str, state: CallState) -> TurnFrame:
        hit = self._known.get(_normalise(turn))
        if hit is None:
            return _uncertain("not an exact repeat of a verified question")
        question, qtype = hit
        return TurnFrame.from_dict({"kind": "general", "subject": "none", "confidence": 1.0,
                                    "question": question, "question_type": qtype})

    def __len__(self) -> int:
        return len(self._known)


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
 "question_type": "policy|how_to|product_fact|place_fact|search|other"}

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
attributes: tier and location from the turn or the call state; changes_answer only if it changes the answer.
uses_state / abstain: resolve "it", "that", "the other place", ellipsis from the call state, the agent's mentions
and last reply. If the referent is not there, abstain = true and kind = dialogue. Never guess.
question: only for general. Standalone and de-identified, built only from words in the turn, the agent's last reply
and the call state. Keep every product, place, condition, quantity, time and negation; drop names, IDs, contacts.
One sentence ending in "?", at most 25 words, generic voice ("How do I reset a password?").
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


__all__ = ["Understander", "ReplayUnderstander", "LLMUnderstander", "WithFallback", "INSTRUCTIONS"]
