"""register_crowkis(): adds the Crowkis provider to Bolna."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type

from bolna import providers

from ...voice_async import async_voice_session
from .errors import CrowkisBolnaError
from .llm import CrowkisLLM
from .turn_filter import TurnFilter

DEFAULT_PROVIDER_NAME = "crowkis"
DEFAULT_BASE_PROVIDER = "openai"
TASK_MANAGER_KEY = "task_manager_instance"

SessionFactory = Callable[[], Any]


def register_crowkis(*, name: str = DEFAULT_PROVIDER_NAME, base: str = DEFAULT_BASE_PROVIDER,
                     session_factory: Optional[SessionFactory] = None,
                     session_options: Optional[Dict[str, Any]] = None) -> Type[CrowkisLLM]:
    """Add a provider called ``name`` to Bolna that puts Crowkis in front of its ``base`` LLM.

    Composition root of the adapter. Use it in an agent with ``"provider": name``. Each
    call gets its own session, made by ``session_factory()``, or by
    ``crowkis.async_voice_session(**session_options)`` (server settings from the
    environment). Registering the same name again replaces it. Raises CrowkisBolnaError
    for an unknown base, one that is already a Crowkis provider, or both factory and options.
    """
    if session_factory is not None and session_options:
        raise CrowkisBolnaError("pass session_factory or session_options, not both")
    registry = providers.SUPPORTED_LLM_PROVIDERS
    base_class = _base_class(registry, name, base)
    factory = session_factory or _options_factory(session_options or {})
    wrapper = _wrapper_class(base, base_class, factory)
    registry[name] = wrapper
    return wrapper


def _base_class(registry: Dict[str, Any], name: str, base: str) -> type:
    if base == name:
        raise CrowkisBolnaError(f"provider {name!r} cannot wrap itself: name it differently from its base")
    if base not in registry:
        raise CrowkisBolnaError(f"Bolna has no LLM provider {base!r} to put Crowkis in front of")
    if issubclass(registry[base], CrowkisLLM):
        raise CrowkisBolnaError(f"provider {base!r} already has Crowkis in front of it")
    return registry[base]


def _options_factory(options: Dict[str, Any]) -> SessionFactory:
    def make_session() -> Any:
        return async_voice_session(**options)

    return make_session


def _wrapper_class(base: str, base_class: type, factory: SessionFactory) -> Type[CrowkisLLM]:
    """A CrowkisLLM subclass that builds its wrapped LLM and session as Bolna builds an LLM."""

    class RegisteredCrowkisLLM(CrowkisLLM):
        """Built by Bolna as ``cls(language=..., **llm_config, **kwargs)``."""

        def __init__(self, **kwargs: Any) -> None:
            inner = base_class(**{**kwargs, "provider": base})
            super().__init__(inner, factory(), task_manager=kwargs.get(TASK_MANAGER_KEY), owns_session=True,
                             turn_filter=TurnFilter.registered())

    RegisteredCrowkisLLM.__name__ = RegisteredCrowkisLLM.__qualname__ = f"Crowkis{base_class.__name__}"
    return RegisteredCrowkisLLM
