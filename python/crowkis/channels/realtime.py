from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from .voice import TurnDecision, VoiceSession

_USER = "user"

_ASSISTANT = "assistant"

_SERVED_ACTIONS = frozenset({"serve", "filler"})


def _render(template: Any, values: Dict[str, str]) -> Any:
    """Copy a message template, putting values into "{role}"/"{text}" strings.

    Whole-string placeholders only, so a caller's words can never inject JSON
    structure or another placeholder into the message sent to the provider.
    """
    if isinstance(template, dict):
        return {k: _render(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_render(v, values) for v in template]
    if isinstance(template, str) and template.startswith("{") and template.endswith("}"):
        return values.get(template[1:-1], template)
    return copy.deepcopy(template)


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
        inject_template: Optional[Dict[str, Any]] = None,
        respond_template: Optional[Dict[str, Any]] = None,
        assistant_role: str = _ASSISTANT,
        inject_user: bool = True,
    ) -> None:
        """Provider event names and message shapes, as data.

        ``inject_template`` / ``respond_template`` are the full messages to send,
        with "{role}" and "{text}" placeholders at any depth — needed wherever a
        provider nests the text (e.g. ``item.content[]`` or ``turns[].parts[]``).
        ``inject_user=False`` for providers that already hold the caller's turn
        (server-side voice activity detection commits the audio as an item);
        injecting it again duplicates it. ``assistant_role`` is the provider's
        name for the model's turns.
        """
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
        self.inject_template = inject_template
        self.respond_template = respond_template
        self.assistant_role = _named(assistant_role, "assistant_role")
        self.inject_user = bool(inject_user)

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
        if self.inject_template is not None:
            return _render(self.inject_template, {"role": role, "text": text})
        return {
            "type": self.inject_event,
            self.role_field: role,
            self.text_field: text,
        }

    def respond(self, text: str = "") -> Dict[str, Any]:
        if self.respond_template is not None:
            return _render(self.respond_template, {"text": text})
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

    def take_pending_audio(self) -> Optional[bytes]:
        """The cached answer's audio for the app to play, handed over once.

        The provider is never asked to speak a cached answer (that would be a
        billed inference), so the app plays this itself — and stops it on
        barge-in, since the provider does not know it is playing.
        """
        audio, self.pending_decision = self.pending_audio, None
        return audio

    def handle(self, event: Any) -> List[Dict[str, Any]]:
        self.events_seen += 1

        # Only an event carrying a transcript string is a turn. A provider that
        # nests transcription inside a general message type also sends audio
        # chunks and turn markers under that type; answering those with a
        # respond event started a new, billed, self-interrupting response each.
        transcript = self.adapter.transcript_of(event)
        if transcript is None:
            # Typed as the transcript event but the text is not where it was
            # expected: a turn still happened, and silence is worse than a bill.
            typed = isinstance(event, dict) and event.get("type") == self.adapter.transcript_event
            return self._forward() if typed else []
        self.pending_decision = None
        if not transcript.strip():
            return self._forward()

        self.transcripts += 1
        try:
            decision = self.session.decide(transcript)
            action = getattr(decision, "action", None)
            spoken = getattr(decision, "text", None)
            if action not in _SERVED_ACTIONS:
                return self._forward(transcript)
            if not isinstance(spoken, str) or not spoken.strip():
                return self._forward(transcript)
            events = [self.adapter.inject(_USER, transcript)] if self.adapter.inject_user else []
            events.append(self.adapter.inject(self.adapter.assistant_role, spoken))
        except Exception:
            return self._forward(transcript)

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

    def _forward(self, transcript: str = "") -> List[Dict[str, Any]]:
        self.forwarded += 1
        return [self.adapter.respond(transcript)]

    def __repr__(self) -> str:
        return (
            f"RealtimeGate(served={self.served}, forwarded={self.forwarded}, "
            f"suppressed={self.suppressed})"
        )


__all__ = ["RealtimeAdapter", "RealtimeGate"]
