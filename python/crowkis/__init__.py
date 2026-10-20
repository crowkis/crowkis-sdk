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
from .voice import TurnDecision, VoiceResponse, VoiceSession, voice_session, warm_from_calls
from .voice_async import AsyncVoiceResponse, AsyncVoiceSession, async_voice_session

# Turn understanding: understand once, check with fixed rules, route by contract.
from .turn import TurnFrame
from .callstate import CallState
from .verify import RuleChecker, Verdict
from .understand import LLMUnderstander, ReplayUnderstander, WithFallback
from .session import CallSession, TurnResult
from .chat import Chat, ChatConflict, ChatReply, MemoryStore

# NOTE: Crowkis is model-agnostic. Use `Crowkis().cached()` / `.ask()` to cache ANY
# model. A thin OpenAI-SDK drop-in still lives at `crowkis.openai_wrapper.CachedOpenAI`
# for that specific convenience, but it is intentionally not a headline export.

__all__ = [
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
    "Chat",
    "ChatReply",
    "ChatConflict",
    "MemoryStore",
    "CallSession",
    "TurnResult",
    "CallState",
    "TurnFrame",
    "RuleChecker",
    "Verdict",
    "LLMUnderstander",
    "ReplayUnderstander",
    "WithFallback",
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
