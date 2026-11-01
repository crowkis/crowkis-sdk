"""What the Voice tab shows for each turn, sent to the browser as RTVI server messages.

The Crowkis processors themselves come from the SDK (crowkis.integrations.pipecat);
these two callbacks only turn what they report into messages for the UI.
"""

import asyncio

from crowkis.privacy import is_context_dependent as _is_context_dependent
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

from pricing import gemini_usd, llm_usd, tts_usd


def _prompt(messages) -> str:
    return " ".join(str(m.get("content", "")) for m in messages)


# --- Who decided: Curva or the rules ---------------------------------------------------
# The Voice tab shows, like Chat, who decided what happens to each answer. A saved answer is
# judged by Curva a moment after it is written: the browser asks POST /api/decision with
# the key below until the verdict lands. A hit carries the verdict of the answer it served.

def _lookup_key(turn: dict) -> str:
    """The key the gate looked this turn up under: the question, or for a follow-up
    "previous question || question" (VoiceSession._context_key)."""
    question = turn["question"]
    if not _is_context_dependent(question.strip()):
        return question
    users = [m.get("content", "") for m in turn["messages"] if m.get("role") == "user"]
    return f"{users[-2]} || {question}" if len(users) >= 2 else question


def _hit_verdict(crowkis, tenant: str, turn: dict) -> dict:
    """What Curva recorded about the answer a hit served. Asked again with the same key
    (CGET returns it; the SDK's decision does not carry it)."""
    key = _lookup_key(turn)
    hit = crowkis.cget_hit(key, tenant=tenant)
    if hit is None:
        return {"cache_key": key}
    return {
        "cache_key": key,
        "verdict": {"judged": hit.judged, "vouched": hit.vouched, "lifetime": hit.lifetime,
                    "commitment": hit.commitment, "ttl": hit.ttl_remaining},
    }


def _saved_key(answer: dict):
    """The key a model answer was stored under, when it was stored."""
    if answer.get("saved") not in ("saved", "template"):
        return None
    users = [m.get("content", "") for m in answer["messages"] if m.get("role") == "user"]
    return " || ".join(users) if len(users) in (1, 2) else None


def _with_decisions(turn_report, answer_report, crowkis, tenant: str):
    async def on_turn_decided(turn: dict) -> RTVIServerMessageFrame:
        frame = await turn_report(turn)
        frame.data["tenant"] = tenant
        if turn["decision"].action == "serve":
            try:
                frame.data.update(await asyncio.to_thread(_hit_verdict, crowkis, tenant, turn))
            except Exception:  # noqa: BLE001 - the verdict is shown, never needed to answer
                pass
        return frame

    async def on_answer_decided(answer: dict) -> RTVIServerMessageFrame:
        frame = await answer_report(answer)
        frame.data["tenant"] = tenant
        frame.data["cache_key"] = _saved_key(answer)
        return frame

    return on_turn_decided, on_answer_decided


def _model_sees(decision):
    """On a miss, what the model read: both pipelines send it exactly decision.messages."""
    if not decision.needs_model:
        return None  # the cache answered
    return ("whole call" if not decision.cacheable
            else "question" if len(decision.messages) == 1 else "question + previous")


def make_reports(pipeline: str, crowkis=None, tenant: str = None):
    """The ``on_turn`` / ``on_answer`` callbacks for one pipeline: ``groq`` or ``gemini``.
    With a Crowkis client, the messages also say who decided (see _with_decisions)."""
    reports = (_gemini_turn, _gemini_answer) if pipeline == "gemini" else (on_turn, on_answer)
    if crowkis is None:
        return reports
    return _with_decisions(*reports, crowkis, tenant)


def _turn(turn: dict, saved_llm: float, saved_tts: float, model_sees) -> RTVIServerMessageFrame:
    decision = turn["decision"]
    return RTVIServerMessageFrame(
        data={
            "type": "crowkis-turn",
            "question": turn["question"],
            "answer": decision.text,  # None on a miss; the model's answer follows as crowkis-answer
            "action": decision.action,  # serve | filler | infer
            "reason": decision.reason,
            "confidence": round(decision.confidence, 4),
            "gate_ms": round(turn["gate_ms"], 1),
            "saved_usd": saved_llm + saved_tts,
            "saved_llm_usd": saved_llm,
            "saved_tts_usd": saved_tts,
            "audio": "cached" if turn["audio_cached"] else ("tts" if decision.text else None),
            "model_sees": model_sees,
            "stats": turn["stats"],
        }
    )


async def on_turn(turn: dict) -> RTVIServerMessageFrame:
    decision = turn["decision"]
    saved_llm = saved_tts = 0.0
    if not decision.needs_model:
        # What the model (and the TTS, when the audio was cached too) would have charged.
        saved_llm = llm_usd(_prompt(turn["messages"]), decision.text)
        saved_tts = tts_usd(decision.text) if turn["audio_cached"] else 0.0
    return _turn(turn, saved_llm, saved_tts, _model_sees(decision))


async def _gemini_turn(turn: dict) -> RTVIServerMessageFrame:
    # Gemini speaks its own answers, so one bill covers the model and the voice. A hit
    # without stored audio is spoken by Sarvam instead, which is a cost, not a saving.
    decision = turn["decision"]
    saved_llm = saved_tts = 0.0
    if not decision.needs_model:
        saved_llm = gemini_usd(_prompt(turn["messages"]), decision.text)
        saved_tts = 0.0 if turn["audio_cached"] else -tts_usd(decision.text)
    return _turn(turn, saved_llm, saved_tts, _model_sees(decision))


async def _gemini_answer(answer: dict) -> RTVIServerMessageFrame:
    cost = gemini_usd(_prompt(answer["messages"]), answer["answer"])
    return RTVIServerMessageFrame(
        data={
            "type": "crowkis-answer",
            "answer": answer["answer"],
            "cost_usd": cost,
            "cost_llm_usd": cost,
            "cost_tts_usd": 0.0,
            "saved": answer.get("saved"),
        }
    )


async def on_answer(answer: dict) -> RTVIServerMessageFrame:
    llm = llm_usd(_prompt(answer["messages"]), answer["answer"])
    tts = tts_usd(answer["answer"])
    return RTVIServerMessageFrame(
        data={
            "type": "crowkis-answer",
            "answer": answer["answer"],
            "cost_usd": llm + tts,
            "cost_llm_usd": llm,
            "cost_tts_usd": tts,
            "saved": answer.get("saved"),
        }
    )
