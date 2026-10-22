"""Channel: what a channel is able to do, as the rules and the turn steps read it (plan §3.3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    """A capability profile. Rules read these fields and never branch on the channel's name.

    ``isolates_context``: the model can be given only the question. ``budget_ms``: the lookup budget
    the factories use. ``audio``: answers have cached clips. ``spoken``: answers are read aloud, so
    screen-only answers are refused. ``saves_answers``: the channel writes answers itself."""

    name: str
    isolates_context: bool
    budget_ms: int
    audio: bool
    spoken: bool
    saves_answers: bool


VOICE = Channel("voice", isolates_context=True, budget_ms=250, audio=True, spoken=True, saves_answers=True)
CHAT = Channel("chat", isolates_context=True, budget_ms=1000, audio=False, spoken=False, saves_answers=True)
REALTIME = Channel("realtime", isolates_context=False, budget_ms=250, audio=False, spoken=True, saves_answers=False)
