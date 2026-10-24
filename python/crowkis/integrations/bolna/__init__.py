"""Crowkis in a Bolna voice agent.

The one-line setup: register the provider once at start-up, then name it in the agent.

    from crowkis.integrations.bolna import register_crowkis

    register_crowkis()                 # adds provider "crowkis", in front of Bolna's "openai" LLM
    # agent config:  "llm_config": {"provider": "crowkis", "model": "gpt-4o-mini", ...}

    register_crowkis(name="crowkis-azure", base="azure", session_options={"latency_budget_ms": 250})

    register_crowkis(synthesizer="elevenlabs")   # also cached voice clips, in front of that synthesizer

Bolna builds one LLM per call and picks its class by provider name. The class registered
here wraps Bolna's own LLM (a Decorator) and owns one Crowkis voice session per call, built
from ``session_options`` (server settings from the CROWKIS_* environment variables) or by
``session_factory``. The same privacy rules as the Pipecat and LiveKit adapters apply.

Cached: a caller's general question. A hit is streamed to Bolna's speech side without
calling the model; on a miss the model reads the app's system prompt and the question alone.

Never cached: a turn with anything personal in it, and everything after a caller told the
call something about themselves (those answers read the whole call and stay in it); tool
calls and their follow-ups; speculative (eager) turns; keypad and language-switch turns;
silence nudges; JSON requests; graph, knowledge-base and multi-agent tasks; an answer that
repeats a caller detail the system prompt holds.

Saved: a model answer is saved only once Bolna has written it to its history in full, so a
reply trimmed or dropped by a barge-in never is. It is settled when the next turn starts
and when the call ends (``close()``).

Voice clips (``synthesizer="<name>"``): a served answer whose clip is cached plays the clip
instead of calling the TTS, and the audio of an answer saved word for word is kept for the
next caller, keyed by voice and format (raw mu-law or PCM only). A reply cut off by a barge-in
keeps no clip. The LLM and the synthesizer of one call find each other through the call's task
manager.

A failure in Crowkis never breaks a call: the model answers instead.

Needs ``bolna`` (0.10.x). Nothing outside this package imports it.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Callable, Dict, Optional, Type

from bolna import providers

from ...client import CrowkisError
from ...voice_async import AsyncVoiceSession, async_voice_session
from .llm import CrowkisLLM
from .synthesizer import CallLinks, CrowkisSynthesizer
from .turn_filter import TurnFilter

__all__ = ["CrowkisLLM", "CrowkisSynthesizer", "register_crowkis", "CrowkisBolnaError"]


class CrowkisBolnaError(CrowkisError):
    """Setting up the Crowkis provider in Bolna failed (an unknown or unusable base provider).

    Never raised during a call: a failure inside a live call fails open to Bolna's own LLM."""

    retryable = False


DEFAULT_PROVIDER_NAME = "crowkis"
DEFAULT_BASE_PROVIDER = "openai"
TASK_MANAGER_KEY = "task_manager_instance"

SessionFactory = Callable[[], AsyncVoiceSession]


def register_crowkis(*, name: str = DEFAULT_PROVIDER_NAME, base: str = DEFAULT_BASE_PROVIDER,
                     session_factory: Optional[SessionFactory] = None,
                     session_options: Optional[Dict[str, Any]] = None,
                     synthesizer: Optional[str] = None) -> Type[CrowkisLLM]:
    """Add a provider called ``name`` to Bolna that puts Crowkis in front of its ``base`` LLM.

    Composition root of the adapter. Use it in an agent with ``"provider": name``. Each
    call gets its own session, made by ``session_factory()``, or by
    ``crowkis.async_voice_session(**session_options)`` (server settings from the
    environment). A factory must return an ``AsyncVoiceSession``: Bolna is fully async, so a
    sync ``VoiceSession`` is not supported. Registering the same name again replaces it. Raises
    CrowkisBolnaError for an unknown base, one that is already a Crowkis provider, or both factory
    and options.

    ``synthesizer`` names one of Bolna's synthesizers (its provider key) to put the audio
    cache in front of as well: cached answers then play their stored voice clip, and the
    audio of answers the cache shares is kept. Bolna validates a synthesizer's provider name,
    so the key keeps its name and its class is replaced by a wrapper; registering again wraps
    the original once. Without it, audio is untouched. Raises CrowkisBolnaError for an
    unknown synthesizer.
    """
    if session_factory is not None and session_options:
        raise CrowkisBolnaError("pass session_factory or session_options, not both")
    registry = providers.SUPPORTED_LLM_PROVIDERS
    base_class = _base_class(registry, name, base)
    synthesizer_class = _synthesizer_class(synthesizer) if synthesizer is not None else None
    factory = session_factory or partial(async_voice_session, **(session_options or {}))
    links = CallLinks()
    wrapper = _wrapper_class(base, base_class, factory, links)
    registry[name] = wrapper
    if synthesizer_class is not None:
        providers.SUPPORTED_SYNTHESIZER_MODELS[synthesizer] = _synthesizer_wrapper_class(synthesizer_class, links)
    return wrapper


def _base_class(registry: Dict[str, Any], name: str, base: str) -> type:
    if base == name:
        raise CrowkisBolnaError(f"provider {name!r} cannot wrap itself: name it differently from its base")
    if base not in registry:
        raise CrowkisBolnaError(f"Bolna has no LLM provider {base!r} to put Crowkis in front of")
    if issubclass(registry[base], CrowkisLLM):
        raise CrowkisBolnaError(f"provider {base!r} already has Crowkis in front of it")
    return registry[base]


def _synthesizer_class(name: str) -> type:
    """Bolna's own class for a synthesizer key (the original, when Crowkis already wraps it)."""
    registry = providers.SUPPORTED_SYNTHESIZER_MODELS
    if name not in registry:
        raise CrowkisBolnaError(f"Bolna has no synthesizer provider {name!r} to put Crowkis in front of")
    registered = registry[name]
    return registered.base_class if issubclass(registered, CrowkisSynthesizer) else registered


def _wrapper_class(base: str, base_class: type, factory: SessionFactory, links: CallLinks) -> Type[CrowkisLLM]:
    """A CrowkisLLM subclass that builds its wrapped LLM and session as Bolna builds an LLM."""

    class RegisteredCrowkisLLM(CrowkisLLM):
        """Built by Bolna as ``cls(language=..., **llm_config, **kwargs)``."""

        def __init__(self, **kwargs: Any) -> None:
            inner = base_class(**{**kwargs, "provider": base})
            super().__init__(inner, factory(), task_manager=kwargs.get(TASK_MANAGER_KEY), owns_session=True,
                             turn_filter=TurnFilter.registered(), links=links)

    RegisteredCrowkisLLM.__name__ = RegisteredCrowkisLLM.__qualname__ = f"Crowkis{base_class.__name__}"
    return RegisteredCrowkisLLM


def _synthesizer_wrapper_class(base_class: type, links: CallLinks) -> Type[CrowkisSynthesizer]:
    """A CrowkisSynthesizer subclass that builds its wrapped synthesizer as Bolna builds one."""

    class RegisteredCrowkisSynthesizer(CrowkisSynthesizer):
        """Built by Bolna as ``cls(**synthesizer_config, **provider_config, **kwargs)``."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(base_class(**kwargs), links)

    RegisteredCrowkisSynthesizer.base_class = base_class
    RegisteredCrowkisSynthesizer.__name__ = RegisteredCrowkisSynthesizer.__qualname__ = f"Crowkis{base_class.__name__}"
    return RegisteredCrowkisSynthesizer
