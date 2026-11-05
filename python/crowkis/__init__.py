__version__ = "0.5.2"  # the same as pyproject.toml and the Node package; tests/test_version.py checks

from .client.commands import (
    AsyncCrowkis,
    AsyncCrowkisClient,
    CacheHit,
    Crowkis,
    CrowkisClient,
    SimResult,
)
from .client.admin import CrowkisAdmin
from .client.connection import CrowkisError
from .client.grpc.grpc_stub import CrowkisGrpcStub, GrpcCacheHit, GrpcStreamChunk

# Dependency-free integration — safe to export at top level.
from .integrations.memory import CrowkisMemory
from ._help import help, render as help_text
from .client.agent import Agent
from .channels.realtime import RealtimeAdapter, RealtimeGate
from .channels.voice_session import TurnDecision, VoiceResponse, VoiceSession, voice_session, warm_from_calls
from .channels.async_voice_session import AsyncVoiceResponse, AsyncVoiceSession, async_voice_session

# Turn understanding: understand once, check with fixed rules, route by contract.
from .understanding.model.frame import TurnFrame
from .state.call_state import CallState
from .understanding.model.understanders import (
    LLMUnderstander,
    WithFallback,
    LLMClassifier,
    LLMRewriter,
)
# Voice understanding slots (v4): a model reads the turn; the word rules still apply.
from .turns.values import CHAT, REALTIME, VOICE, Channel
# Where a turn goes: public, stable names (crowkis.privacy has the privacy word rules).
from .turns.results import AGENT, FILLER, PERSONAL, SHARED, TASK, TOOLS, URGENT

# NOTE: Crowkis is model-agnostic. Use `Crowkis().cached()` / `.ask()` to cache ANY
# model. A thin OpenAI-SDK drop-in still lives at `crowkis.integrations.openai.CachedOpenAI`
# for that specific convenience, but it is intentionally not a headline export.

__all__ = [
    "__version__",
    "Agent",
    "VoiceSession",
    "VoiceResponse",
    "AsyncVoiceSession",
    "AsyncVoiceResponse",
    "async_voice_session",
    "voice_session",
    "TurnDecision",
    "warm_from_calls",
    "RealtimeAdapter",
    "RealtimeGate",
    # turn understanding
    "CallState",
    "TurnFrame",
    "LLMUnderstander",
    "WithFallback",
    "LLMClassifier",
    "LLMRewriter",
    "Channel",
    "VOICE",
    "CHAT",
    "REALTIME",
    "AGENT",
    "FILLER",
    "PERSONAL",
    "SHARED",
    "TASK",
    "TOOLS",
    "URGENT",
    # clients (idiomatic short names first)
    "Crowkis",
    "AsyncCrowkis",
    "CrowkisClient",
    "AsyncCrowkisClient",
    # types
    "CacheHit",
    "SimResult",
    "CrowkisError",
    "CrowkisAdmin",
    # agent memory + discovery
    "CrowkisMemory",
    "help",
    "help_text",
    # gRPC surface
    "CrowkisGrpcStub",
    "GrpcCacheHit",
    "GrpcStreamChunk",
]

# LangChain lives in crowkis.integrations.langchain and is imported explicitly by
# users who installed the extra: `from crowkis.integrations.langchain import CrowkisCache`.
# It is intentionally NOT imported here so `import crowkis` never requires LangChain.
