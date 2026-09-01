from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .voice import TurnDecision, VoiceSession

_USER = "user"

_ASSISTANT = "assistant"

_SERVED_ACTIONS = frozenset({"serve", "filler"})


def _named(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{label} must be a non-empty string naming the event your realtime "
            "provider actually uses. A wrong or missing name means the gate never "
            "fires, every turn is billed, and nothing reports it"
        )
    return value.strip()


class RealtimeAdapter:

    def __init__(
        self,
        *,
        transcript_event: str,
        transcript_field: str,
        inject_event: str,
        respond_event: str,
        role_field: str = "role",
        text_field: str = "text",
    ) -> None:
        self.transcript_event = _named(transcript_event, "transcript_event")
        self.transcript_field = _named(transcript_field, "transcript_field")
        self.inject_event = _named(inject_event, "inject_event")
        self.respond_event = _named(respond_event, "respond_event")
        self.role_field = _named(role_field, "role_field")
        self.text_field = _named(text_field, "text_field")
        path: Tuple[str, ...] = tuple(
            part.strip() for part in self.transcript_field.split(".")
        )
        if not all(path):
            raise ValueError(
                "transcript_field must be a field name or a dotted path to one, "
                f"got {transcript_field!r}"
            )
        self.transcript_path = path

    def is_transcript(self, event: Any) -> bool:
        if not isinstance(event, dict):
            return False
        return (
            event.get("type") == self.transcript_event
            or self.transcript_event in event
        )

    def transcript_of(self, event: Any) -> Optional[str]:
        if not self.is_transcript(event):
            return None
        node: Any = event
        for key in self.transcript_path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node if isinstance(node, str) else None

    def inject(self, role: str, text: str) -> Dict[str, Any]:
        return {
            "type": self.inject_event,
            self.role_field: role,
            self.text_field: text,
        }

    def respond(self) -> Dict[str, Any]:
        return {"type": self.respond_event}

    def __repr__(self) -> str:
        return (
            f"RealtimeAdapter(transcript_event={self.transcript_event!r}, "
            f"transcript_field={self.transcript_field!r})"
        )


class RealtimeGate:

    def __init__(self, session: VoiceSession, adapter: RealtimeAdapter) -> None:
        if not isinstance(adapter, RealtimeAdapter):
            raise TypeError(
                "RealtimeGate needs a RealtimeAdapter carrying this provider's event "
                f"names, got {type(adapter).__name__}"
            )
        if not callable(getattr(session, "decide", None)):
            raise TypeError(
                "RealtimeGate needs a VoiceSession to decide each turn, got "
                f"{type(session).__name__}"
            )
        self.session = session
        self.adapter = adapter
        self.events_seen = 0
        self.transcripts = 0
        self.served = 0
        self.forwarded = 0
        self.suppressed = 0
        self.pending_decision: Optional[TurnDecision] = None

    @property
    def pending_audio(self) -> Optional[bytes]:
        return getattr(self.pending_decision, "audio", None)

    def handle(self, event: Any) -> List[Dict[str, Any]]:
        self.events_seen += 1
        self.pending_decision = None

        if not self.adapter.is_transcript(event):
            return []

        transcript = self.adapter.transcript_of(event)
        if not transcript or not transcript.strip():
            return self._forward()

        self.transcripts += 1
        try:
            decision = self.session.decide(transcript)
            action = getattr(decision, "action", None)
            spoken = getattr(decision, "text", None)
            if action not in _SERVED_ACTIONS:
                return self._forward()
            if not isinstance(spoken, str) or not spoken.strip():
                return self._forward()
            events = [
                self.adapter.inject(_USER, transcript),
                self.adapter.inject(_ASSISTANT, spoken),
            ]
        except Exception:
            return self._forward()

        self.pending_decision = decision
        self.served += 1
        self.suppressed += 1
        return events

    def stats(self) -> dict:
        return {
            "events": self.events_seen,
            "transcripts": self.transcripts,
            "served": self.served,
            "forwarded": self.forwarded,
            "suppressed": self.suppressed,
        }

    def _forward(self) -> List[Dict[str, Any]]:
        self.forwarded += 1
        return [self.adapter.respond()]

    def __repr__(self) -> str:
        return (
            f"RealtimeGate(served={self.served}, forwarded={self.forwarded}, "
            f"suppressed={self.suppressed})"
        )


__all__ = ["RealtimeAdapter", "RealtimeGate"]
