"""F8 step 3: replays Chat's golden inputs through voice_session(channel="chat") and lists every turn Chat
kept private (or refused to save) that voice would share or save.

Run from python/:  PYTHONPATH=.:tests/golden:tests python ../v4-notes/tools/f8_chat_replay.py [--stub] [--json out.json]
``--stub`` plugs in a stub LLM (LLMClassifier + LLMRewriter over the frozen stand-in frames)."""
import json
import sys

from crowkis import voice_session
from crowkis.understanding.model.understanders import LLMClassifier, LLMRewriter
from golden.replay import AGENT_ID, INPUTS, GoldenStore, ScriptedUnderstander, _sees, golden_path, replay, suites

STUB = "--stub" in sys.argv


class ChatOnVoiceReplay:
    pipeline = "chat-on-voice"
    pool = "kb=1"

    def call(self, store, call):
        store.tenant = None
        options = {}
        if STUB:
            understander = ScriptedUnderstander(INPUTS["frames"])
            options = {"classifier": LLMClassifier(understander), "rewriter": LLMRewriter(understander)}
        session = voice_session(client=store, channel="chat", agent_id=AGENT_ID, latency_budget_ms=None,
                                understand_budget_ms=None, **options)
        turns = []
        for turn in call["turns"]:
            decision = session.decide(turn["say"])
            record = {"say": turn["say"], "action": decision.action, "rule": decision.rule,
                      "sees": _sees(decision.messages)}
            if decision.needs_model:
                if turn.get("barge_in"):
                    session.cancel()
                decision = session.record(decision, turn["reply"])
                record.update(stored=decision.stored, save_rule=decision.save_rule, not_stored=decision.not_stored)
            turns.append(record)
        return {"turns": turns}


def main():
    findings = []
    totals = {"turns": 0, "chat_private_or_refused": 0}
    for suite, calls in suites().items():
        chat = json.loads(golden_path("chat", suite).read_text("utf-8"))["calls"]
        voice = replay(ChatOnVoiceReplay(), calls)["calls"]
        for cid, call in chat.items():
            for index, turn in enumerate(call["turns"]):
                other = voice[cid]["turns"][index]
                totals["turns"] += 1
                outcome = turn.get("outcome")
                chat_private = turn["route"] != "shared" or turn["sees"] is None
                chat_refused = turn["route"] == "shared" and isinstance(outcome, str) and outcome.startswith("refused")
                if not (chat_private or chat_refused):
                    continue
                totals["chat_private_or_refused"] += 1
                voice_shares = other["sees"] is not None and other["action"] == "infer"
                voice_saves = bool(other.get("stored"))
                if (chat_private and (voice_shares or voice_saves)) or (chat_refused and voice_saves):
                    findings.append({"suite": suite, "call": cid, "turn": index, "say": turn["say"],
                                     "chat": [turn["route"], turn["reason"], outcome],
                                     "voice": [other["action"], other["rule"], other["sees"] is not None,
                                               other.get("stored"), other.get("not_stored")]})
    print(json.dumps(totals), "differences:", len(findings))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as out:
            json.dump(findings, out, indent=1, ensure_ascii=False)


main()
