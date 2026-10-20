"""CallSession: one call or chat thread on turn understanding v2.2 (part 4).

Ties the pieces together for each caller turn:

    understand (model slot) -> rule checker -> route -> [lookup] -> answer -> save check
                                                                         -> call state update

Routes
  urgent    the app's ``on_urgent`` hook runs first; the agent answers; never cached
  task      a step of a booking/order the agent is running; the agent answers; never cached
  shared    looked up; a hit is spoken; on a miss the model reads ONLY the shared question,
            and its answer is saved after the save check, with the question type's expiry
  personal  the agent answers with its tools; a verified single-field value may be phrased
            by a registered response shape (``phrase``), never fetched or decided by the cache
  tools     live data or an action: the agent answers with its tools; never cached
  agent     everything else (dialogue, chit-chat, unclear): the agent answers; never cached

Sits next to VoiceSession; existing users are unaffected.
"""

from __future__ import annotations

import concurrent.futures
import copy
import re
import string
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .callstate import IDENTITIES, CallState, word_digest
from .voice import _instructs, _proper_nouns, _is_non_answer as is_non_answer, _repeats_prompt_details, _tells_about_caller, _urgent, _words
from .turn import NOT_GENERAL_TYPES, TurnFrame
from .understand import ReplayUnderstander, Understander
from .verify import _FUNCTION, _NUMWORDS, AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT, RuleChecker, Verdict

FILLER = "filler"
# Phrases a name follows ("my name is sarah", "call me raj", "this is priya"). "I'm" is not
# one here: "I'm allergic" is a fact, not a name, and the shared question may carry it.
_NAME_LEADS = (("name", "is"), ("call", "me"), ("this", "is"))
# "I'm Sarah" / "i am sarah, ...": the word after is a name when capitalised, or when the phrase ends
# with it; in a turn telling a fact only when "and" or a comma follows ("I'm diabetic." is the fact).
_SELF_INTRO = re.compile(r"\b[Ii](?:['’]m| am|m)\s+([^\W\d_]+)(\s*(?:[,.!?;]|$)|\s+(?:and|from|here|calling|speaking)\b)?")
_DAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
# Words a person's name follows ("my colleague JOSE", "my son Arjun", "my teacher Mr Smith"): after
# my/our/his/her/their/your, the next capitalised word is a name whatever the model tagged it as.
_RELATIONS = frozenset("colleague coworker friend son daughter wife husband partner mother mom mum father dad brother sister boss manager kid child baby grandma grandpa grandmother grandfather uncle aunt cousin neighbour neighbor roommate girlfriend boyfriend fiance fiancee teacher doctor client customer".split())
_POSSESSIVE = frozenset("my our his her their your s".split())  # "s": "my wife's sister PRIYA"
_TITLES = frozenset("mr mrs ms miss dr sir madam".split())
_CALENDAR = frozenset("january february march april may june july august september october november december".split()
                      + _DAYS + [d + "s" for d in _DAYS])


def _names(text: str, frame: Optional[TurnFrame] = None, fact: bool = True) -> List[str]:
    """What names the caller in a turn: emails, long numbers, a name after "my name is", what the
    understanding model tagged as identifying, and, in a turn that is not telling a fact, any name
    it gives ("hi i'm sarah"). A fact turn keeps its words ("I'm allergic"): the question carries them."""
    words = _words(text)
    found = set()
    for named in _EMAIL.findall(text) + _LONG_DIGITS.findall(text):
        found.update(_words(named))
    for i in range(len(words)):
        for lead in _NAME_LEADS:
            end = i + len(lead)
            if tuple(words[i:end]) == lead and end < len(words) and words[end] not in _FUNCTION:
                found.add(words[end])
    for t in frame.identifying_texts if frame else ():
        found.update(_words(t))
    tokens = re.findall(r"[^\W\d_]+", text)
    for i in range(1, len(tokens) - 1):
        if tokens[i].lower() in _RELATIONS and tokens[i - 1].lower() in _POSSESSIVE:
            nxt = tokens[i + 1]
            # "Mr Smith", "O'Brien": the name is the word after the title or the one-letter part.
            for word in tokens[i + 1:i + 3] if nxt.lower() in _TITLES or len(nxt) == 1 else [nxt]:
                low = word.lower()
                if word != "I" and low not in _FUNCTION and low not in _CALENDAR and \
                        any(unicodedata.category(c) in ("Lu", "Lt") for c in word):
                    found.add(low)
    for m in _SELF_INTRO.finditer(text):
        word = m.group(1)
        closer = None if m.group(2) is None else m.group(2).strip()
        if word.lower() not in _FUNCTION and (word[0].isupper() or (closer is not None and (not fact or closer in (",", "and")))):
            found.add(word.lower())
    return sorted(found)


def _told(text: str, frame: TurnFrame) -> Tuple[Set[str], List[str]]:
    """A turn telling a fact, in two parts: what names the caller (never kept, never in a shared
    question) and the details a shared question must carry: a short number, a month or day, a
    place or thing the understanding model tagged ("3", "December", "Goa"). Any other capitalised
    word, a sentence's first included ("Priya and I..."), is a name AND a detail: a question can
    never both carry it and leave it out, so a chat whose model tagged nothing stays private."""
    words = _words(text)
    named = set(_names(text, frame))
    tagged = {w for e in frame.entities if not e.identifying and e.type != "other_person" for w in _words(e.text)}
    capitalised = {w.lower() for w in re.findall(r"[^\W\d_]+", text) if w[0].isupper() and w != "I"} - _FUNCTION
    untagged = {w for w in capitalised if w not in _CALENDAR and w not in tagged}
    named |= untagged | {w for w in words if any(c.isdecimal() for c in w) and len(w) > 3}
    details = ({w for w in words if any(c.isdecimal() for c in w)} | capitalised) - named
    return named, sorted(details | untagged)


def _private_words(text: str, frame: Optional[TurnFrame] = None) -> List[str]:
    """Everything in a turn that may identify the caller: its names, any number, any capitalised
    word. Broad on purpose; it only ever refuses a shared answer, so a wrong guess costs a hit."""
    found = {w for w in _words(text) if any(c.isdecimal() for c in w)} | _proper_nouns(text)
    return sorted(found | set(_names(text, frame)))
MODES = ("full", "replay_only", "off")
Message = Dict[str, str]
_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-call")
_UNDERSTAND = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-understand")
_TRIM = string.punctuation + string.whitespace
_EMAIL = re.compile(r"\S+@\S+")
_LONG_DIGITS = re.compile(r"\d(?:[\s-]?\d){5,}")
# A reply to a private turn is kept between turns only to follow the conversation: names,
# emails and numbers in it are masked first (any word with a capital, a digit, or a letter of a
# script without case).
_REPLY_WORD = re.compile(r"\S+@\S+|\w+")
_MASKED = frozenset(("Lu", "Lt", "Lo", "Nd", "Nl", "No"))


def _masked(reply: Any) -> str:
    return _REPLY_WORD.sub(lambda m: "_" if "@" in m.group() or any(
        unicodedata.category(c) in _MASKED for c in m.group()) else m.group(), str(reply or ""))
# A first-person claim that something was done. A cached answer must never claim an action.
_ACTION_CLAIM = re.compile(
    r"\b(i\s*(have|'ve)|i\s+just|we\s*(have|'ve))\s+(cancel+ed|booked|refunded|processed|changed|updated|"
    r"reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\b"
    r"|\b(has|have)\s+been\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted)\b", re.I)


@dataclass
class TurnResult:
    turn_id: int
    route: str
    text: Optional[str] = None             # what to say now (cache hit or filler), else None
    needs_model: bool = True
    messages: Optional[List[Message]] = None  # what the model reads; None = the whole call
    frame: Optional[TurnFrame] = None
    verdict: Optional[Verdict] = None
    reason: str = ""

    @property
    def served_from_cache(self) -> bool:
        return self.route == SHARED and self.text is not None


@dataclass
class _Shape:
    template: str
    requires: str


class CallSession:
    """One call. Not thread-safe: one turn at a time (barge-in via ``cancel``).

    ``agent``         a crowkis Agent (lookup and save go through ``ask`` / ``learn``)
    ``understander``  anything with ``understand(turn, state) -> TurnFrame``
    ``on_urgent``     called with (turn, frame) before anything else on an urgent turn
    ``understand_budget_ms``  hard limit on the understanding step; past it (or on any error)
                      the safe fallback (``replay``, exact repeats only) decides, or the agent
                      answers. A late frame is never used.
    ``latency_budget_ms``     hard limit on the cache lookup; past it the model answers.
    ``mode``          "full" (default), "replay_only" (no model: exact repeats of verified
                      questions only) or "off" (share nothing). Switchable at runtime with
                      ``set_mode``: the kill switch for production.
    ``on_event``      monitoring hook, called with a dict after each turn ("turn") and each
                      recorded answer ("answer"). Carries routes, reasons and de-identified keys,
                      never the caller's raw words. Errors in the hook are ignored.
    ``instructions``  the system prompt the model reads with a shared question. A shared
                      answer that repeats a detail it gives about this caller ("Hi Asha!")
                      is never saved (``refused:prompt_detail``).
    """

    def __init__(
        self,
        agent: Any,
        understander: Understander,
        *,
        checker: Optional[RuleChecker] = None,
        on_urgent: Optional[Callable[[str, TurnFrame], None]] = None,
        replay: Optional[ReplayUnderstander] = None,
        serve_above: float = 0.92,
        latency_budget_ms: Optional[float] = 300.0,
        understand_budget_ms: Optional[float] = 250.0,
        fillers: Optional[Dict[str, str]] = None,
        mode: str = "full",
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        urgent_reply: Optional[str] = None,
        on_tools: Optional[Callable[[str, TurnFrame], Optional[str]]] = None,
        instructions: str = "",
    ) -> None:
        for name, value in (("latency_budget_ms", latency_budget_ms), ("understand_budget_ms", understand_budget_ms)):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or None, got {value}")
        self.agent = agent
        self.understander = understander
        self.checker = checker or RuleChecker()
        self.on_urgent = on_urgent
        self.replay = replay
        self.serve_above = serve_above
        self.latency_budget_ms = latency_budget_ms
        self.understand_budget_ms = understand_budget_ms
        self.on_event = on_event
        # The business's pre-approved reply to an emergency (its helplines); without one the
        # model answers with the whole call. Never cached either way.
        self.urgent_reply = (urgent_reply or "").strip() or None
        # The business's own system for "my balance", "my booking": returns the reply, or None
        # for the model to answer with the whole call. Never cached.
        self.on_tools = on_tools
        self.instructions = (instructions or "").strip()
        self.mode = "full"
        self.set_mode(mode)
        self.state = CallState()
        self._fillers = {self._norm(k): v for k, v in (fillers or {}).items()}
        self._shapes: Dict[str, _Shape] = {}
        self._next = 1
        self._open: Optional[TurnResult] = None
        self._cancelled: set = set()
        self.counts: Dict[str, int] = {k: 0 for k in (
            URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved", "save_refused",
            "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
            "cancelled", "sharing_off", "tools_answered")}

    def set_mode(self, mode: str) -> None:
        """Switch sharing at runtime: "full", "replay_only" (no model) or "off" (share nothing)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self.mode = mode

    # --- one caller turn --------------------------------------------------------------

    def handle(self, turn: str) -> TurnResult:
        tid, self._next = self._next, self._next + 1
        text = " ".join((turn or "").split())
        if not text:
            return self._open_turn(TurnResult(tid, AGENT, reason="empty"))
        filler = self._fillers.get(self._norm(text))
        if filler is not None:
            self.counts[FILLER] += 1
            self.state.note_agent_reply(filler)
            return TurnResult(tid, FILLER, text=filler, needs_model=False, reason="registered filler")

        if self.mode == "off":
            self.counts["sharing_off"] += 1
            result = self._open_turn(TurnResult(tid, AGENT, reason="sharing off"))
            self._emit({"type": "turn", "turn_id": tid, "route": AGENT, "reasons": ["mode_off"], "shared": False})
            return result
        # What the caller tells (an allergy, an age, a trip) must reach every later shared
        # question, this turn's included: noted before the check, in fixed code.
        words = _words(text)
        about_caller = _tells_about_caller(text)
        frame = self._understand(text)
        named: Set[str] = set()
        if about_caller:
            named, details = _told(text, frame)
            self.state.note_stated(" ".join(w for w in words if w not in named))
            self.state.note_details(details)
        # On every turn and before the check: a name given in this very turn ("Hi, I'm Sarah.
        # What is the refund policy?") is never in a shared question or answer.
        names = sorted(set(_names(text, frame, fact=about_caller)) | named)
        self.state.note_names(names)
        if frame.language and _instructs(text, words):
            self.state.language = frame.language  # "reply only in Hindi": kept for the rest of the chat
        verdict = self.checker.check(frame, text, self.state)
        if verdict.shared and self._carries_private_word(verdict.question):
            verdict = Verdict(False, AGENT, ["V5_private_word"])
        elif verdict.shared and self._drops_a_detail(verdict.question):
            verdict = Verdict(False, AGENT, ["V7_lost_detail"])
        elif verdict.shared and self._names_someone_untagged(verdict.question, frame):
            verdict = Verdict(False, AGENT, ["V5_untagged_name"])
        if verdict.route != URGENT and about_caller and _urgent(words):
            verdict = Verdict(False, URGENT, ["V1_urgent_fixed"])  # never left to the model alone
        self.state.apply(frame, shared=verdict.shared)
        self.state.note_private((_private_words(text, frame) if not verdict.shared else []) + names)
        self.counts[verdict.route] += 1

        if verdict.route == URGENT and self.on_urgent is not None:
            try:
                self.on_urgent(text, frame)
            except Exception:  # noqa: BLE001 - the hook must not take the call down
                pass
        if verdict.route == URGENT and self.urgent_reply:
            self.state.note_agent_reply(self.urgent_reply)
            return TurnResult(tid, URGENT, text=self.urgent_reply, needs_model=False, frame=frame,
                              verdict=verdict, reason="urgent script")
        if verdict.route in (TOOLS, PERSONAL) and self.on_tools is not None:
            try:
                answered = self.on_tools(text, frame)
            except Exception:  # noqa: BLE001 - a failing tool means the model answers
                answered = None
            if answered:
                self.counts["tools_answered"] += 1
                self.state.note_agent_reply(_masked(answered))
                return TurnResult(tid, verdict.route, text=answered, needs_model=False, frame=frame,
                                  verdict=verdict, reason="answered by the business's tools")
        event = {"type": "turn", "turn_id": tid, "route": verdict.route, "reasons": list(verdict.reasons),
                 "shared": verdict.shared, "urgent": frame.urgent, "kind": frame.kind,
                 "confidence": frame.confidence, "question": verdict.question, "key": verdict.key,
                 "question_type": frame.question_type if verdict.shared else None}
        if verdict.route != SHARED:
            self._emit(dict(event, hit=False))
            return self._open_turn(TurnResult(tid, verdict.route, frame=frame, verdict=verdict,
                                              reason=";".join(verdict.reasons)))

        if self.replay is not None:
            self.replay.remember(text, verdict.question, frame.question_type)
        hit = self._lookup(verdict.key, verdict.segment)
        if hit is not None:
            self.counts["hits"] += 1
            result = TurnResult(tid, SHARED, text=hit, needs_model=False, frame=frame, verdict=verdict,
                                reason="cache hit")
            self.state.note_agent_reply(hit)
            self._emit(dict(event, hit=True))
            return self._open_turn(result)
        self._emit(dict(event, hit=False))
        messages = [{"role": "user", "content": verdict.question}]
        notes = []
        if verdict.attributes:
            notes.append("Answer for: " + "; ".join(f"{k}: {v}" for k, v in sorted(verdict.attributes.items())) + ".")
        language = self.state.language or frame.language
        if language:
            notes.append(f"Reply in this language: {language}.")
        if notes:
            messages.insert(0, {"role": "system", "content": " ".join(notes)})
        return self._open_turn(TurnResult(tid, SHARED, frame=frame, verdict=verdict, messages=messages,
                                          reason="cache miss"))

    def _carries_private_word(self, question: Optional[str]) -> bool:
        """The shared question says what named the caller earlier ("for sarah")."""
        return any(self.state.is_name(w) for w in _words(question or ""))

    def _names_someone_untagged(self, question: Optional[str], frame: TurnFrame) -> bool:
        """A word in the shared question with a capital ("Priya", "PRIYA", "McKenzie"), or in a script
        without capitals, that the understanding model did not tag as a place, thing or topic, that is
        no month or day, and that no earlier shared turn of this chat said. Fixed code cannot tell
        "Priya" from "France" or "SSO"; the model's tag can (it is asked to tag every one)."""
        allowed = {w for e in frame.entities if not e.identifying and e.type not in NOT_GENERAL_TYPES
                   for w in _words(e.text)}
        allowed |= _CALENDAR | set(_words(self.state.active_question or "")) | set(_words(self.state.last_reply))
        flagged = set()
        for i, word in enumerate(re.findall(r"[^\W\d_]+", question or "")):
            low = word.lower()
            if word == "I" or (i == 0 and low in _FUNCTION):  # "What ...", "How ..."
                continue
            if any(unicodedata.category(c) in ("Lu", "Lt", "Lo") for c in word):
                flagged.add(low)
        return any(w not in allowed and word_digest(w) not in self.state.details for w in flagged)

    def _drops_a_detail(self, question: Optional[str]) -> bool:
        """A place, month or number the caller told ("Goa in December") is missing from the question."""
        words = _words(question or "")
        asked = {word_digest(w) for w in words} | {word_digest(_NUMWORDS.get(w, w)) for w in words}  # "three" is "3"
        return any(d not in asked for d in self.state.details)

    def record_answer(self, result: TurnResult, answer: str, *, mentions: tuple = (),
                      task: Optional[str] = None) -> str:
        outcome = self._record(result, answer, mentions, task)
        self._emit({"type": "answer", "turn_id": result.turn_id, "route": result.route, "outcome": outcome,
                    "key": result.verdict.key if result.verdict else None})
        return outcome

    def _record(self, result: TurnResult, answer: str, mentions: tuple, task: Optional[str]) -> str:
        """The agent answered ``result``. Saves it when allowed and updates the call state.

        ``mentions`` are the places/products/options the agent named; ``task`` is set when
        the agent starts collecting details for a booking, order or account change.
        Returns what happened: saved | not_shared | refused:<why> | cancelled | stale.
        """
        if result.turn_id in self._cancelled:
            self.counts["cancelled"] += 1
            return "cancelled"
        if self._open is None or self._open.turn_id != result.turn_id:
            return "stale"  # an older turn finishing after a newer one started: never saved
        self._open = None
        kept = answer if result.route == SHARED else _masked(answer)
        self.state.note_agent_reply(kept, mentions, task)
        if result.route != SHARED or result.text is not None or result.verdict is None:
            return "not_shared"
        why = self.save_check(answer, result.verdict, result.frame)
        if why:
            self.counts["save_refused"] += 1
            return "refused:" + why
        try:
            self.agent.learn(result.verdict.key, answer, ttl=result.verdict.ttl, segment=result.verdict.segment)
        except Exception:  # noqa: BLE001 - a refused write must not end a call
            self.counts["save_refused"] += 1
            return "refused:write_failed"
        self.counts["saved"] += 1
        return "saved"

    def cancel(self) -> bool:
        """Barge-in: the open turn is abandoned and its answer will never be saved."""
        if self._open is None:
            return False
        self._cancelled.add(self._open.turn_id)
        self._open = None
        return True

    # --- personal answers: phrasing a verified value, never fetching or deciding it -----

    def register_shape(self, field_name: str, template: str, *, requires: str = "identified") -> None:
        """A response shape for one field returned by the agent's own tools,
        e.g. ``register_shape("eta", "Your order arrives on {eta}.", requires="identified")``."""
        if requires not in IDENTITIES:
            raise ValueError(f"requires must be one of {IDENTITIES}")
        if "{" + field_name + "}" not in template:
            raise ValueError("the template must contain the field's own slot")
        self._shapes[field_name] = _Shape(template, requires)

    def phrase(self, field_name: str, value: Any, *, subject: str = "self") -> Optional[str]:
        """Phrase a value the agent's tool returned for this caller. None when there is no
        shape, the caller is not verified enough, or the value is about someone else."""
        shape = self._shapes.get(field_name)
        if shape is None or subject != "self" or value in (None, ""):
            return None
        if IDENTITIES.index(self.state.identity) < IDENTITIES.index(shape.requires):
            return None
        return shape.template.replace("{" + field_name + "}", str(value))

    # --- the save check -----------------------------------------------------------------

    def save_check(self, answer: str, verdict: Verdict, frame: Optional[TurnFrame] = None) -> Optional[str]:
        """Why an answer to a shared question must not be saved, or None."""
        text = " ".join((answer or "").split())
        if not text:
            return "empty"
        if is_non_answer(text):
            return "non_answer"
        if _EMAIL.search(text) or _LONG_DIGITS.search(text):
            return "identifying"
        if frame is not None and any(t.lower() in text.lower() for t in frame.identifying_texts):
            return "identifying"
        if _ACTION_CLAIM.search(text):
            return "action_claim"
        for name, attr in self.state.attributes.items():
            pattern = r"\b" + re.escape(attr.value) + r"\b" if attr.value else None
            # A value the question itself says ("the capital of France") is part of what was asked.
            if name not in verdict.attributes and pattern and re.search(pattern, text, re.I) \
                    and not re.search(pattern, verdict.question or "", re.I):
                return "attribute_not_in_key"
        # A word that identified the caller in a turn that was not shared ("Sarah", "55512")
        # is never in a shared answer, unless the shared question itself has it.
        asked = set(_words(verdict.question or ""))
        if any(w not in asked and self.state.is_private(w) for w in _words(text)):
            return "private_word"
        if self.instructions and _repeats_prompt_details(text, verdict.question or "", self.instructions,
                                                         self._prompt_key()):
            return "prompt_detail"
        return None

    def _prompt_key(self) -> tuple:
        """Which system prompts this call's is compared with: the same agent's on the same
        channel (a chat's prompt never stands in for a voice call's)."""
        agent = self.agent
        tenant = getattr(agent, "tenant", None) or getattr(getattr(agent, "_client", None), "tenant", None)
        return (tenant, getattr(agent, "agent_id", None), getattr(self.checker, "channel", None))

    # --- saved with the chat thread ----------------------------------------------------------

    def export(self) -> Dict[str, Any]:
        """The thread's memory for the app's store, between turns. No transcript is in it."""
        return {"version": 1, "state": self.state.to_dict(), "next_turn": self._next}

    @classmethod
    def restore(cls, agent: Any, understander: Understander, data: Optional[Dict[str, Any]],
                **options: Any) -> "CallSession":
        """A session for the next turn of a thread saved with ``export``. Missing or damaged
        data starts a fresh thread; it never raises."""
        session = cls(agent, understander, **options)
        data = data if isinstance(data, dict) else {}
        session.state = CallState.from_dict(data.get("state"))
        try:
            session._next = max(1, int(data.get("next_turn", 1)))
        except (TypeError, ValueError, OverflowError):
            pass
        return session

    # --- internals ----------------------------------------------------------------------

    def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 - monitoring must never affect the call
            pass

    def _open_turn(self, result: TurnResult) -> TurnResult:
        self._open = result
        return result

    def _understand(self, text: str) -> TurnFrame:
        """The model's frame within the budget; otherwise the safe fallback's, or an uncertain one."""
        if self.mode == "replay_only":
            if self.replay is None:
                return TurnFrame.from_dict(None)
            self.counts["fallback_used"] += 1
            return self.replay.understand(text, self.state)
        try:
            if self.understand_budget_ms is None:
                return self.understander.understand(text, self.state)
            # The worker gets its own copy of the state: a late model must never see (or race
            # with) the state of a later turn. Its late answer is simply discarded.
            state = copy.deepcopy(self.state)
            return _UNDERSTAND.submit(self.understander.understand, text, state).result(
                timeout=self.understand_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self.counts["understand_timeouts"] += 1
        except Exception:  # noqa: BLE001 - understanding failing must never end a call
            self.counts["understand_errors"] += 1
        if self.replay is not None and self.replay is not self.understander:
            self.counts["fallback_used"] += 1
            try:
                return self.replay.understand(text, self.state)
            except Exception:  # noqa: BLE001
                pass
        return TurnFrame.from_dict(None)

    def _lookup(self, key: str, segment: Optional[str]) -> Optional[str]:
        call = lambda: self.agent.ask(key, serve_above=self.serve_above,  # noqa: E731
                                      cheap_above=min(0.6, self.serve_above), segment=segment)
        try:
            if self.latency_budget_ms is None:
                hit = call()
            else:
                hit = _LOOKUPS.submit(call).result(timeout=self.latency_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self.counts["lookup_timeouts"] += 1
            return None
        except Exception:  # noqa: BLE001 - an unreachable cache means "ask the model"
            self.counts["lookup_errors"] += 1
            return None
        if hit.get("route") == "cache" and hit.get("answer"):
            return hit["answer"]
        return None

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").lower().strip(_TRIM).split())

    def stats(self) -> dict:
        return dict(self.counts)


__all__ = ["CallSession", "TurnResult", "FILLER", "MODES"]
