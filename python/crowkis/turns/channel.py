"""Channel: what a channel is able to do, as the rules and the turn steps read it (plan §3.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Union


@dataclass(frozen=True)
class Channel:
    """A capability profile. Rules read these fields and never branch on the channel's name.

    ``isolates_context``: the model can be given only the question. ``budget_ms``: the lookup budget
    the factories use. ``understand_budget_ms``: how long a plugged-in classifier and rewriter may
    take on a turn before the word rules read it instead. ``audio``: answers have cached clips.
    ``spoken``: answers are read aloud, so screen-only answers are refused. ``saves_answers``: the
    channel writes answers itself."""

    name: str
    isolates_context: bool
    budget_ms: int
    audio: bool
    spoken: bool
    saves_answers: bool
    understand_budget_ms: int = 250

    @classmethod
    def of(cls, channel: Union["Channel", str]) -> "Channel":
        """A channel, or the profile with that name ("voice", "chat", "realtime")."""
        if isinstance(channel, Channel):
            return channel
        try:
            return CHANNELS[str(channel).strip().lower()]
        except KeyError:
            raise ValueError(f"channel must be one of {sorted(CHANNELS)} or a Channel, got {channel!r}") from None


VOICE = Channel("voice", isolates_context=True, budget_ms=250, audio=True, spoken=True, saves_answers=True)
CHAT = Channel("chat", isolates_context=True, budget_ms=1000, audio=False, spoken=False, saves_answers=True)
REALTIME = Channel("realtime", isolates_context=False, budget_ms=250, audio=False, spoken=True, saves_answers=False)

CHANNELS: Dict[str, Channel] = {channel.name: channel for channel in (VOICE, CHAT, REALTIME)}
