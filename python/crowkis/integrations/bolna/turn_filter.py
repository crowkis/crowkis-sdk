"""Which Bolna LLM calls are a caller's turn Crowkis may answer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from ...voice_turns import _field, _tool_context

SILENCE_NUDGE_PREFIX = "[silence]"
TRANSCRIBER_ORIGIN = "transcriber"
AUTO_TOOL_CHOICE = "auto"
CALLER_ROLE = "user"
TOOL_ROLE = "tool"
# Agent types whose prompts are per node or per document: never a shared question and answer.
UNCACHEABLE_AGENT_TYPES = frozenset({"graph_agent", "knowledgebase_agent", "multiagent"})


@dataclass(frozen=True)
class GenerateCall:
    """What Bolna passed to one ``generate_stream`` call, plus the agent type of its task."""

    messages: List[Any]
    synthesize: bool
    request_json: bool
    meta_info: Optional[dict]
    tool_choice: Any
    tools: Any
    agent_type: Optional[str]
    has_call_context: bool = True

    @property
    def meta(self) -> dict:
        """The call's meta_info, empty when Bolna passed none."""
        return self.meta_info or {}

    @property
    def last_role(self) -> Optional[str]:
        """The role of the last message."""
        return _field(self.messages[-1], "role") if self.messages else None

    @property
    def last_text(self) -> str:
        """The last message's text (a content list's text parts are joined)."""
        content = _field(self.messages[-1], "content") if self.messages else None
        if isinstance(content, list):
            return " ".join(str(_field(part, "text") or "") for part in content)
        return content if isinstance(content, str) else ""

    @property
    def caller_text(self) -> Optional[str]:
        """What the caller said, when the last message is theirs."""
        return self.last_text if self.last_role == CALLER_ROLE else None


class BypassRule:
    """One reason a call is not a caller turn. Subclasses set ``name`` and ``applies``."""

    name = "rule"

    def applies(self, call: GenerateCall) -> bool:
        """Whether this call must go to the model untouched."""
        raise NotImplementedError


class ToolFollowUp(BypassRule):
    """The model's continuation after a tool ran, or a follow-up to a parent response."""

    name = "tool_follow_up"

    def applies(self, call: GenerateCall) -> bool:
        return call.last_role == TOOL_ROLE or bool(call.meta.get("parent_response_uid"))


class ToolContext(BypassRule):
    """A tool call or result sits after the caller's last words."""

    name = "tool_context"

    def applies(self, call: GenerateCall) -> bool:
        return _tool_context(list(call.messages))


class ForcedToolChoice(BypassRule):
    """The call asks the model to use a tool."""

    name = "forced_tool_choice"

    def applies(self, call: GenerateCall) -> bool:
        return bool(call.tool_choice) and call.tool_choice != AUTO_TOOL_CHOICE


class EagerEndOfTurn(BypassRule):
    """A speculative answer to a turn the caller may not have finished."""

    name = "eager_end_of_turn"

    def applies(self, call: GenerateCall) -> bool:
        return bool(call.meta.get("eager_eot"))


class NonTranscriberOrigin(BypassRule):
    """Not speech: keypad digits or a language-switch guess."""

    name = "non_transcriber_origin"

    def applies(self, call: GenerateCall) -> bool:
        origin = call.meta.get("origin")
        return origin is not None and origin != TRANSCRIBER_ORIGIN


class UnsequencedCall(BypassRule):
    """Sequence id -1: Bolna's marker for a call that is not a spoken turn."""

    name = "unsequenced"

    def applies(self, call: GenerateCall) -> bool:
        return call.meta.get("sequence_id") == -1


class SilenceNudge(BypassRule):
    """Bolna's own prompt after the caller went quiet."""

    name = "silence_nudge"

    def applies(self, call: GenerateCall) -> bool:
        return call.last_text.lstrip().lower().startswith(SILENCE_NUDGE_PREFIX)


class JsonRequest(BypassRule):
    """A structured-output call: never a spoken answer."""

    name = "json_request"

    def applies(self, call: GenerateCall) -> bool:
        return bool(call.request_json)


class OtherAgentType(BypassRule):
    """Graph, knowledge-base and multi-agent tasks answer from their own prompts."""

    name = "agent_type"

    def applies(self, call: GenerateCall) -> bool:
        return call.agent_type in UNCACHEABLE_AGENT_TYPES


class NotTheCaller(BypassRule):
    """The last message is not the caller's words."""

    name = "not_the_caller"

    def applies(self, call: GenerateCall) -> bool:
        return call.last_role != CALLER_ROLE


class NoCallContext(BypassRule):
    """An LLM Bolna built outside the conversation task: no history and no agent type to judge it by."""

    name = "no_call_context"

    def applies(self, call: GenerateCall) -> bool:
        return not call.has_call_context


class TurnFilter:
    """Chain of Responsibility: the first rule that applies names why a call is left alone."""

    def __init__(self, rules: Sequence[BypassRule]) -> None:
        self._rules = tuple(rules)

    @classmethod
    def standard(cls) -> "TurnFilter":
        """The rules for a Bolna conversation task."""
        return cls([ToolFollowUp(), ToolContext(), ForcedToolChoice(), EagerEndOfTurn(), NonTranscriberOrigin(),
                    UnsequencedCall(), SilenceNudge(), JsonRequest(), OtherAgentType(), NotTheCaller()])

    @classmethod
    def registered(cls) -> "TurnFilter":
        """The standard rules plus ``NoCallContext``, for wrappers that ``register_crowkis`` builds."""
        return cls([*cls.standard()._rules, NoCallContext()])

    def bypass_rule(self, call: GenerateCall) -> Optional[str]:
        """The name of the rule that bypasses this call, or None for a caller turn."""
        for rule in self._rules:
            if rule.applies(call):
                return rule.name
        return None
