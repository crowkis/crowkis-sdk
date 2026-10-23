"""The SDK's privacy word rules, by public, stable names, for apps and tools that reuse them.

These names do not change when the SDK's internals move; import them from here, never from a module inside
``crowkis.understanding``."""

from .understanding.word_rules import (
    _CONTEXT_BOUND_THRESHOLD as CONTEXT_BOUND_THRESHOLD,
    _SLOT as SLOT,
    _abstract as abstract,
    _fill as fill,
    _is_context_dependent as is_context_dependent,
    _is_personal as is_personal,
    _leaks as leaks,
)

__all__ = ["CONTEXT_BOUND_THRESHOLD", "SLOT", "abstract", "fill", "is_context_dependent", "is_personal", "leaks"]
