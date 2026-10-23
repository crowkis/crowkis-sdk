"""VoiceSaving: the save check and the write of a voice call's answers, as TurnCore's Saving."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..understanding.call_readings import CallReadings
from .answered import VoiceAnswered
from .checked import Checked
from .decision import _Outcome
from .model_answer import ModelAnswer
from .turn_host import TurnHost
from .voice_call import VoiceCall
from .voice_report import VoiceReport

if TYPE_CHECKING:
    from ..rules.rule_set import RuleSet

SAVED = "saved"
TEMPLATE = "template"


class VoiceSaving:
    """check(): the answer as the save rules read it: ``answer_given`` first, then, once it is known
    to be an answer, its cache key and its place in the transcript, then ``before_sharing``.
    write(): the shared form of the answer and its write, inside TurnCore's write boundary: a personal
    answer only as a shape with this call's values taken out (``personal``), any other after the
    ``sharing`` rules, through the bounded write, with the question it was saved for."""

    def __init__(self, host: TurnHost, *, rules: "RuleSet", call: VoiceCall, call_readings: CallReadings,
                 report: VoiceReport) -> None:
        self._host = host
        self._rules = rules
        self._call = call
        self._call_readings = call_readings
        self._report = report

    def check(self, answered: VoiceAnswered) -> Checked:
        answer = ModelAnswer(answered.said, answered.model_said, None, self._call, private=answered.private,
                             instructions=answered.instructions,
                             cacheable=answered.shareable and not answered.private)
        verdict = self._rules.answer_given.first_objection(answer)
        if verdict is not None:
            return Checked(answer, verdict)
        answer = answer.keyed(self._call_readings.rewritten(answer.text)
                              or self._host.context_key(answered.said, answer.text))
        self._host.transcript.append({"role": "user", "content": answered.said})
        self._host.transcript.append({"role": "assistant", "content": answered.model_said})
        return Checked(answer, self._rules.before_sharing.first_objection(answer))

    def write(self, answer: ModelAnswer) -> _Outcome:
        if answer.is_personal:
            return self._write_personal(answer)
        verdict = self._rules.sharing.first_objection(answer)
        if verdict is not None:
            return self._report.kept(verdict)
        slow = self._host.learn(answer.key, answer.answer, ttl=self._host.ttl)
        self._host.note_stored(answer.key)
        if slow is None:  # a slow server gets no extra write
            self._host.keep_question(answer.key, answer.answer)
        return slow or _Outcome(SAVED)

    def _write_personal(self, answer: ModelAnswer) -> _Outcome:
        """A personal answer is shared only as a shape with this call's values taken out."""
        personal = self._rules.personal
        verdict = personal.check(answer)
        if verdict is None:
            templated = self._host.learn_personal(answer.key, answer.answer)
            if isinstance(templated, _Outcome):
                return templated  # slow_write: the shape was not confirmed written
            if templated:
                return _Outcome(TEMPLATE)
            verdict = personal.refusal()
        return self._report.kept(verdict)
