__version__ = "0.5.2"  # the same as pyproject.toml and the Node package; tests/test_version.py checks

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
from .channels.realtime import RealtimeAdapter, RealtimeGate
from .channels.voice_session import TurnDecision, VoiceResponse, VoiceSession, voice_session, warm_from_calls
from .channels.async_voice_session import AsyncVoiceResponse, AsyncVoiceSession, async_voice_session

# Turn understanding: understand once, check with fixed rules, route by contract.
from .understanding.turn_frame import TurnFrame
from .state.call_state import CallState
from .rules.rule_checker import RuleChecker, Verdict
from .understanding.understanders import LLMUnderstander, ReplayUnderstander, WithFallback
# Voice understanding slots (v4): a model reads the turn; the word rules still apply.
from .understanding.llm_classifier import LLMClassifier
from .understanding.llm_rewriter import LLMRewriter
from .understanding.replay_rewriter import ReplayRewriter
from .turns.channel import CHAT, REALTIME, VOICE, Channel
# Where a turn goes: public, stable names (crowkis.privacy has the privacy word rules).
from .turns.routes import AGENT, FILLER, PERSONAL, SHARED, TASK, TOOLS, URGENT
from .channels.call_session import CallSession, TurnResult
from .channels.chat import Chat, ChatConflict, ChatReply, MemoryStore

# NOTE: Crowkis is model-agnostic. Use `Crowkis().cached()` / `.ask()` to cache ANY
# model. A thin OpenAI-SDK drop-in still lives at `crowkis.openai_wrapper.CachedOpenAI`
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
    "LLMClassifier",
    "LLMRewriter",
    "ReplayRewriter",
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
