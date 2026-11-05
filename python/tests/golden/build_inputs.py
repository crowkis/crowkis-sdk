"""Builds fixtures/golden/inputs.json, the frozen input of the golden decision files (v4 P0).

Run once, by hand, from python/: ``python tests/golden/build_inputs.py <crowkis-testing-scripts dir>``.
It reads the v1 and v2 voice stress cases and the replies recorded in earlier runs, so the
golden files never depend on another repository at test time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
INPUTS = ROOT / "fixtures" / "golden" / "inputs.json"
CONFORMANCE = ROOT / "fixtures" / "adapter-conformance.json"
FALLBACK_REPLY = "Here is the answer."
CASE_FILES = {"v1": "text_injection_only_v1.json", "v2": "text_injection_only_v2.json"}
# Earlier runs whose recorded replies stand in for the model, per suite, most trusted first.
RUNS = {
    "v1": ["20261016-160921"],
    "v2": ["20261021-165200-partial", "20261022-070930-partial"],
}
# Contact details in the stress cases that look real are swapped for obviously fake ones of
# the same shape, so the fixtures never carry a real-looking number or address.
FAKE_CONTACTS = {
    "98200 55117": "90000 11111",
    "98111 40404": "90000 22222",
    "99887 76655": "90000 33333",
    "harpreet.gill@yahoo.in": "harpreet.gill@example.com",
    "rahul@gmail.com": "rahul@example.com",
}
def fake_contacts(text: str) -> str:
    for real_looking, fake in FAKE_CONTACTS.items():
        text = text.replace(real_looking, fake)
    return text


def recorded_replies(results_dir: Path, suite: str) -> Dict[str, Dict[int, str]]:
    replies: Dict[str, Dict[int, str]] = {}
    for run in RUNS[suite]:
        data = json.loads((results_dir / run / "results.json").read_text("utf-8"))
        for pipeline in data["runs"].values():
            for call_id, call in pipeline.items():
                for turn in call.get("turns", []):
                    reply = turn.get("reply")
                    if isinstance(reply, str) and reply.strip():
                        replies.setdefault(call_id, {}).setdefault(turn["n"], reply)
    return replies


def stress_calls(tests_dir: Path, suite: str) -> List[Dict]:
    cases = json.loads((tests_dir / "voice_stress_cases" / CASE_FILES[suite]).read_text("utf-8"))
    replies = recorded_replies(tests_dir / "voice_stress_results" / "text_injection_only", suite)
    calls = []
    for conversation in cases["conversations"]:
        known = replies.get(conversation["id"], {})
        turns = [{"say": fake_contacts(turn["say"]), "reply": fake_contacts(known.get(n, FALLBACK_REPLY))}
                 for n, turn in enumerate(conversation["turns"], start=1)]
        calls.append({"id": conversation["id"], "turns": turns})
    return calls


def conformance_calls() -> List[Dict]:
    """The conformance scenarios, each on its own store (with its seed and reworded questions);
    the fault mode that depends on timing (slow) is left out, a server that is down is kept."""
    scenarios = json.loads(CONFORMANCE.read_text("utf-8"))["scenarios"]
    calls = []
    for scenario in scenarios:
        if scenario.get("server") == "slow":
            continue
        seed = [{"question": question, "answer": answer} for question, answer in (scenario.get("seed") or {}).items()]
        for index, call in enumerate(scenario["calls"]):
            turns = [{"say": turn["say"], "reply": "".join(turn.get("reply") or []) or FALLBACK_REPLY,
                      "tool": bool(turn.get("tool")), "barge_in": "barge_in_after" in turn}
                     for turn in call]
            calls.append({"id": f"{scenario['name']} #{index + 1}", "store": scenario["name"],
                          "seed": seed, "aliases": scenario.get("aliases") or {},
                          "down": scenario.get("server") == "down", "turns": turns})
    return calls


def _guard_call(name: str, seed: List[Dict], say: str, *, aliases: Optional[Dict[str, str]] = None,
                options: Optional[Dict] = None, engine: bool = False, reply: str = FALLBACK_REPLY) -> Dict:
    return {"id": name, "store": name, "seed": seed, "aliases": aliases or {}, "engine": engine,
            "options": options or {}, "turns": [{"say": say, "reply": reply}]}


REFUNDS = "what is your refund policy"
REFUNDS_REWORDED = "how do refunds work at your shop"
REFUND_ANSWER = "Refunds take five business days."
SHORT = "opening hours"
ORDER = "when will my order arrive"


def hit_guard_calls() -> List[Dict]:
    """One call per hit rule (and the save rules a stored shape or a declared value reach), on a
    store seeded with the cached answer and its flags. Hand-written: the stress calls rarely hit."""
    commitment = [{"question": REFUNDS, "answer": REFUND_ANSWER, "commitment": True}]
    return [
        _guard_call("commitment, same words", commitment, REFUNDS),
        _guard_call("commitment, reworded", commitment, REFUNDS_REWORDED, aliases={REFUNDS_REWORDED: REFUNDS}),
        _guard_call("commitment, reworded, served by choice", commitment, REFUNDS_REWORDED,
                    aliases={REFUNDS_REWORDED: REFUNDS}, options={"commitments": "serve"}),
        _guard_call("an answer written for a screen",
                    [{"question": REFUNDS, "answer": "See https://example.com/refunds for details."}], REFUNDS),
        _guard_call("a server placeholder in the answer",
                    [{"question": REFUNDS, "answer": "We emailed pii_email_a1b2 the refund receipt."}], REFUNDS),
        _guard_call("a short turn, not vouched", [{"question": SHORT, "answer": "Nine to five."}], SHORT,
                    options={"short_turns": True}, engine=True),
        _guard_call("a short turn, vouched", [{"question": SHORT, "answer": "Nine to five.", "vouched": True}],
                    SHORT, options={"short_turns": True}, engine=True),
        _guard_call("a shape with a slot this call has no value for",
                    [{"question": ORDER, "answer": "Your order arrives on {eta}.", "template": True}], ORDER,
                    options={"values": {"name": "Asha"}}),
        _guard_call("a shape filled with this call's value",
                    [{"question": ORDER, "answer": "Your order arrives on {eta}.", "template": True}], ORDER,
                    options={"values": {"eta": "Tuesday"}}),
        _guard_call("a personal answer stored as a shape", [], ORDER,
                    options={"values": {"eta": "Tuesday"}, "share_templates": True},
                    reply="Your order arrives on Tuesday."),
        _guard_call("an answer holding a declared value", [], "how do I reset my password",
                    options={"values": {"code": "4471"}}, reply="Your code is 4471, use it on the reset page."),
    ]


def main(testing_scripts: str) -> None:
    tests_dir = Path(testing_scripts) / "demo" / "voice-agent" / "tests"
    suites = {"stress-v1": stress_calls(tests_dir, "v1"), "stress-v2": stress_calls(tests_dir, "v2"),
              "conformance": conformance_calls(), "hit-guards": hit_guard_calls()}
    inputs = {
        "about": "Frozen input of the golden decision files (v4 P0), built by python/tests/golden/build_inputs.py "
                 "from the v1/v2 voice stress cases, replies recorded in earlier runs, and "
                 "fixtures/adapter-conformance.json, plus hand-written hit-guard calls.",
        "suites": suites,
    }
    INPUTS.parent.mkdir(parents=True, exist_ok=True)
    INPUTS.write_text(json.dumps(inputs, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{INPUTS}: {sum(len(c) for c in suites.values())} calls")


if __name__ == "__main__":
    main(sys.argv[1])
