"""Commitment policies: how a cached commitment (a price, a refund, a policy) may be spoken."""

from __future__ import annotations

from typing import Callable, Dict

from ...turns.hit import Hit

# Strategy per VoiceSession(commitments=...) setting: serve any match, only the same question, or never.
COMMITMENT_POLICIES: Dict[str, Callable[[Hit], bool]] = {
    "serve": lambda hit: True,
    "exact": lambda hit: hit.exact,
    "never": lambda hit: False,
}
