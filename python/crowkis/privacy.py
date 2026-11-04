"""The SDK's privacy word rules, by public, stable names, for apps and tools that reuse them.

These names do not change when the SDK's internals move; import them from here, never from a module inside
``crowkis.understanding``."""

from .understanding.word_rules.answers import _SLOT as SLOT, _abstract as abstract, _fill as fill
from .understanding.word_rules.follow_up import _is_context_dependent as is_context_dependent
from .understanding.word_rules.personal import _leaks as leaks, _is_personal as is_personal
from .understanding.word_rules.text import _CONTEXT_BOUND_THRESHOLD as CONTEXT_BOUND_THRESHOLD

__all__ = ["CONTEXT_BOUND_THRESHOLD", "SLOT", "abstract", "fill", "is_context_dependent", "is_personal", "leaks"]
