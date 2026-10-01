from .client import (
    AsyncCrowkis,
    AsyncCrowkisClient,
    CacheHit,
    Crowkis,
    CrowkisAdmin,
    CrowkisClient,
    CrowkisError,
    SimResult,
)
from .grpc_stub import CrowkisGrpcStub, GrpcCacheHit, GrpcStreamChunk

# Dependency-free integration — safe to export at top level.
from .integrations.memory import CrowkisMemory
from ._help import help, render as help_text
from .agent import Agent
from .realtime import RealtimeAdapter, RealtimeGate
from .conversation import Conversation, Saving, TurnPlan
from .rules import is_context_dependent, is_non_answer, is_personal
from .voice import TurnDecision, VoiceSession

# NOTE: Crowkis is model-agnostic. Use `Crowkis().cached()` / `.ask()` to cache ANY
# model. A thin OpenAI-SDK drop-in still lives at `crowkis.openai_wrapper.CachedOpenAI`
# for that specific convenience, but it is intentionally not a headline export.

__all__ = [
    "Agent",
    # one conversation's cache decisions (chat or voice), and the rules under them
    "Conversation",
    "TurnPlan",
    "Saving",
    "is_personal",
    "is_context_dependent",
    "is_non_answer",
    "VoiceSession",
    "TurnDecision",
    "RealtimeAdapter",
    "RealtimeGate",
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
