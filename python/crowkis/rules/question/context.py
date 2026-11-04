"""Stage 1 rules (question): what the call said before (a private chain, a follow-up, a reference, stated facts)."""

from __future__ import annotations

from typing import Iterator, Optional

from ...runtime.stats import Counter
from ...state.call_state import word_digest
from ...turns.values import Verdict
from ...turns.voice.turn import VoiceTurn
from ...turns.chat.turn import ChatTurn
from ...understanding.chat_details import _unnamed
from ...understanding.fact_relevance import FactRelevanceCheck
from ...understanding.frame_words import (
    _CLAUSE_START,
    _CONTRACTION,
    _FUNCTION,
    _GENERIC_FACT,
    _NUMWORDS,
    _QUESTION_WORDS,
    _REFERRING,
    _stem,
    _toks,
)
from ...understanding.turn_frame import DETAIL_TYPES
from ...understanding.word_rules.call_context import _sets_context
from ...understanding.word_rules.follow_up import _leans_on, _private_chain
from ...understanding.word_rules.text import _words


PRIVATE_CHAIN_REASON = (
    "a follow-up to a private turn of this call: its answer depends on "
    "what this caller said, so it is never answered from a shared cache"
)


class PrivateChain:
    """A follow-up to a private turn of the call, or any turn after an urgent one, is private:
    its answer depends on what this caller said."""

    name = "PrivateChain"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        chain = turn.call.chain() or []
        follows_private = turn.is_context_dependent and (
            _private_chain(chain, turn.call.min_words) or any(turn.call.is_personal(earlier) for earlier in chain))
        if not (follows_private or turn.call.after_urgent(turn.text)):
            return None
        return Verdict(self.name, PRIVATE_CHAIN_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


NO_KEY_REASON = (
    "the utterance only has meaning against an earlier turn and this "
    "call has none, so no cache key can be built for it"
)


class FollowUpWithoutContext:
    """A follow-up ("and what about that") with no earlier turn to lean on has no cache key."""

    name = "FollowUpWithoutContext"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if turn.key is not None:
            return None
        return Verdict(self.name, NO_KEY_REASON, (Counter.INFERRED,))


# The UnresolvedReference rule (stage 1, question; Chat, V10).
class UnresolvedReference:
    """The model says the turn leans on the chat ("how far is it from London?") but the turn or its
    question says "it" and the question names nothing new from the chat (a neutral "population"
    names nothing; "Who is their president?" -> "Who is the president?" dropped it): the reference
    was not resolved. A rewrite that resolved it ("Is it safe to eat pad thai in Thailand?") keeps
    a filler "it" and is fine."""

    name = "UnresolvedReference"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        qwords, said = set(_toks(turn.question)), set(_toks(turn.text))
        named = {w for w in qwords - said if w not in _FUNCTION and w not in _QUESTION_WORDS and w not in _CONTRACTION}
        # shortcut: Chat checks only the last shared question; after a personal turn this misses (as before).
        leans = _leans_on(turn.question, turn.state.active_question or "")
        if not (leans or turn.frame.uses_state and (qwords | said) & _REFERRING and not named):
            return None
        return Verdict(self.name, "V10_unresolved")


TAINTED_REASON = (
    "the caller has told this call something a later answer may depend on "
    "(a condition, an age, a plan, an instruction, a step in their own task); "
    "a shared answer to the bare question could be wrong for them"
)


class CallContextTaint:
    """Once the caller tells the call something a later answer may depend on (a condition, an
    age, a plan, an instruction), every later turn of the call is private. The voice default
    until an understander can tell which stated facts change an answer."""

    name = "CallContextTaint"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not (turn.call.tainted or _sets_context(turn.text)):
            return None
        turn.call.mark_tainted()
        return Verdict(self.name, TAINTED_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


# The StatedFacts rule (stage 1, question; Chat, V7).
class StatedFacts:
    """A fact the caller stated in this chat (an allergy, an age, a trip) that the question does
    not carry. Fixed code, so the allergy case never rests on the model having tagged the
    allergy: the question must keep at least one content word of each such turn. A turn with no
    readable word (another script) cannot be checked, so it keeps the question private.

    v4: a stated turn the frame confidently tags as not changing this answer may be left out
    (``FactRelevanceCheck``); an allergy, a medication, a pregnancy or an age never may."""

    name = "StatedFacts"
    floor = False

    def __init__(self, relevance: Optional[FactRelevanceCheck] = None) -> None:
        self._relevance = relevance if relevance is not None else FactRelevanceCheck()

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        for dropped in self._dropped_statements(turn.state, turn.question):
            if not self._relevance.irrelevant(dropped, turn.frame):
                return Verdict(self.name, "V7_lost:" + dropped)
        return None

    @staticmethod
    def _dropped_statements(state, question) -> Iterator[str]:
        qstems = {_stem(w) for w in _toks(question)}
        for turn in state.stated:
            words = [w for w in _toks(turn) if w not in _FUNCTION and (len(w) > 2 or w.isdigit())]
            # "allergies" alone does not carry "allergic to penicillin": the specific word must be there.
            words = [w for w in words if _stem(w) not in _GENERIC_FACT] or words
            if not words or not any(_stem(w) in qstems for w in words):
                yield turn
                continue
            if StatedFacts._drops_a_listed_item(turn, qstems):
                yield turn

    @staticmethod
    def _drops_a_listed_item(turn: str, qstems) -> bool:
        """Every item of a list is carried: "penicillin and peanuts" is not "peanuts"."""
        toks = _toks(turn)
        for i, w in enumerate(toks):
            # "and I live alone" starts a new clause; it is not a list.
            if w in ("and", "or") and (i + 1 == len(toks) or toks[i + 1] not in _CLAUSE_START):
                for side in (reversed(toks[:i]), toks[i + 1:]):
                    item = next((x for x in side if x not in _FUNCTION), None)
                    if item and (len(item) > 2 or item.isdigit()) and _stem(item) not in _GENERIC_FACT \
                            and _stem(item) not in qstems:
                        return True
        return False


# The StatedFacts rule for voice with an understander (stage 1, question).
TELLS_REASON = "the turn tells the call something a later answer may depend on; its own answer stays with this caller"
DEPENDS_REASON = (
    "the caller told this call something that may change this answer (or the model could not say it does "
    "not); a shared answer to the bare question could be wrong for them"
)


def _hidden(stated: str, private) -> bool:
    """The model was sent this stated turn with a number or a content word masked ("flying to _ with _
    bags"), so it judged the turn without it: the turn counts."""
    stems = FactRelevanceCheck._content_stems
    return any(c.isdecimal() for c in stated) or bool(stems(stated) - stems(_unnamed(stated, private)))


class VoiceStatedFacts:
    """Replaces CallContextTaint when an understander is plugged in: a turn that tells the call
    something (a condition, an age, a plan) stays private, and so does each later turn unless the
    model is sure that none of the stated facts changes its answer and none is an allergy, a
    medication, a pregnancy or an age. Unsure, late or failed: private, as before. Instead of
    tainting the call, it keeps just that turn private (``mark_private``)."""

    name = "VoiceStatedFacts"
    floor = False

    def __init__(self, relevance: Optional[FactRelevanceCheck] = None) -> None:
        self._relevance = relevance if relevance is not None else FactRelevanceCheck()

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if _sets_context(turn.text):
            return self._private(turn, TELLS_REASON)
        if turn.call.tainted:  # the call heard something its model never read (loaded history, a private turn)
            return self._private(turn, DEPENDS_REASON)
        private = turn.call.private_words()
        if any(_hidden(stated, private) or not self._relevance.irrelevant(stated, turn.frame)
               for stated in turn.call.stated()):
            return self._private(turn, DEPENDS_REASON)
        return None

    def _private(self, turn: VoiceTurn, reason: str) -> Verdict:
        turn.call.mark_private(turn.text)
        return Verdict(self.name, reason, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


# The ToldDetailDropped rule (stage 1, question; Chat, "V7_lost_detail", checked once the rule checker would share).
class ToldDetailDropped:
    """A place, month or number the caller told ("Goa in December") is missing from the question."""

    name = "ToldDetailDropped"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        words = _words(turn.question or "")
        asked = {word_digest(w) for w in words} | {word_digest(_NUMWORDS.get(w, w)) for w in words}  # "three" is "3"
        if not any(d not in asked for d in turn.state.details):
            return None
        return Verdict(self.name, "V7_lost_detail")


# The LostDetail rule (stage 1, question; Chat, V7).
class LostDetail:
    """An answer-relevant detail of the turn (a product, a time, a place) missing from the key."""

    name = "LostDetail"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        lost = self._lost_detail(turn.frame, turn.question)
        if lost is None:
            return None
        return Verdict(self.name, "V7_lost:" + lost)

    @staticmethod
    def _lost_detail(frame, question) -> Optional[str]:
        qstems = {_stem(w) for w in _toks(question)}
        attr_text = " ".join(f"{a.value} {a.normalised}" for a in frame.attributes.values()).lower()
        for e in frame.entities:
            if e.answer_relevant and not e.identifying and e.type in DETAIL_TYPES:
                words = [w for w in _toks(e.text) if w not in _FUNCTION]
                if words and not any(_stem(w) in qstems for w in words) and not any(w in attr_text for w in words):
                    return e.text
        return None
