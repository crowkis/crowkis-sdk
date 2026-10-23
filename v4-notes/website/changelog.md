---
title: Changelog
path: /changelog
---

# Changelog

Every release of the Crowkis server and SDKs, newest first. The server image and both SDKs share a version number.

| Version | Server image | Python (`crowkis`) | Node (`@crowkis/client`) | Date |
|---|---|---|---|---|
| **0.5.2** | `crowkis/crowkis:0.5.2` | 0.5.2 | 0.5.2 | *set at release* |
| 0.5.1 | `crowkis/crowkis:0.5.1` | 0.5.0 | 0.5.0 | *date to be filled in by the release owner* |
| 0.5.0 | — | 0.5.0 | 0.5.0 | 2026-07-19 |

## 0.5.2

**Upgrading:**
- Ports are `6383` (cache), `6384` (dashboard), `6385` (gRPC) and `6386` (probes).
- `CROWKIS_AUTH_TOKEN` is the one secret. `CROWKIS_ADMIN_KEY` is retired and ignored.
- The embedding model changed, so cached entries re-warm once.

### Voice agents (new)
- **Plug-in adapters:**
  - Pipecat: `CrowkisLLM` / `CrowkisTTS`.
  - LiveKit Agents for Python: `CrowkisVoice`.
  - LiveKit Agents for Node: `withCrowkis`.
  - Your own loop: `session.respond()`, in Python and Node.
  - See [Voice agents](/docs/voice).
- **`crowkis.voice_session()` / `voiceSession()`** sets up live-call defaults in one call:
  - a 250 ms lookup budget;
  - a 1 s timeout;
  - saves that never hold a turn for more than 500 ms.
- **Streaming:** `respond()` streams your LLM's words to the TTS and saves the answer when the stream ends.
- **Async:** `crowkis.async_voice_session()` for asyncio apps.
- **Audio:** cached answers come with their audio, keyed per voice, language, speed and format. An audio error never breaks a call.
- **Privacy:** one caller's private details never reach another caller. These all stay in that call:
  - a turn about the caller's own records;
  - every turn after the caller tells the call something an answer depends on;
  - an answer built from a tool's result;
  - an answer that repeats a caller detail from the system prompt;
  - cut-off questions and interrupted answers.
- **Every adapter passes one shared test suite** (11 scenarios, Python and Node), on a test server and a real one.

### Chat apps (new)
- **`Chat`** caches a chat app's answers safely. Each message becomes one stand-alone question that carries what the user said earlier. Anything personal, urgent, part of a booking or unclear is never shared.
- **`segment=`** keeps answers in different reply languages or regions apart.

### SDKs
- **Settings from the environment:** `CROWKIS_HOST`, `CROWKIS_PORT`, `CROWKIS_AUTH_TOKEN`, `CROWKIS_TENANT` and `CROWKIS_URL`. A value in code still wins.
- **Node:** ES-module imports work (`import { Crowkis } from "@crowkis/client"`), with types for every subpath. An idle client no longer keeps the process alive.
- **Python 3.9+, Node 18+.**

### Server
- **A redesigned, read-only dashboard** with a year of hourly and daily metrics.
- **Licences** from the command line or `.env` (`CROWKIS_LICENSE_KEY`).
- **The decision engine (Curva)** on any model, in one command: `crowkis curva setup`.
- **The Voice add-on:** spoken answers replayed from the server's audio cache.
- **One auth token** for every surface.
- **Security and compliance fixes.**

## 0.5.1
- The server image used by the 0.5.0 SDKs.

## 0.5.0
- The first public SDK releases on PyPI and npm: the semantic cache (`cached`, `ask`, `lookup`, `store`, `stream`), agent memory, and LangChain / LangChain.js integrations.
