"""A support agent on CallSession (turn understanding v2.2), in the terminal.

Type as the caller; the agent answers from the shared cache when it safely can, otherwise from
the LLM. Every turn prints the route and why, so you can see the decisions.

Needs a Crowkis server and any OpenAI-compatible chat endpoint. Configure with env vars
(keep secrets in a gitignored .env, never in code):

    CROWKIS_HOST=127.0.0.1  CROWKIS_PORT=6383  CROWKIS_TENANT=demo
    LLM_BASE_URL=https://api.openai.com/v1   LLM_API_KEY=...   LLM_MODEL=gpt-4o-mini

    python examples/call_session_agent.py
"""

import json
import os
import urllib.request

from crowkis import Agent, CallSession, CrowkisClient, LLMUnderstander, ReplayUnderstander, WithFallback

BUSINESS = (
    "An online clothing store (shirts, jeans, boots, jackets). Store policies, shipping, returns, "
    "membership benefits and how to use the site are general knowledge. The customer's own orders, "
    "account and refunds are personal. Cancelling, refunding or changing something is an action."
)
SYSTEM = {"role": "system", "content": "You are a friendly support agent for an online clothing store. "
                                       "Answer in one or two short sentences."}


def complete(messages, max_tokens=400):
    """One chat completion from any OpenAI-compatible endpoint (no extra dependencies)."""
    body = json.dumps({"model": os.environ["LLM_MODEL"], "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    req = urllib.request.Request(os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "Authorization": "Bearer " + os.environ["LLM_API_KEY"],
                                                     "User-Agent": "crowkis-example"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def main():
    client = CrowkisClient(host=os.getenv("CROWKIS_HOST", "127.0.0.1"), port=int(os.getenv("CROWKIS_PORT", "6383")),
                           tenant=os.getenv("CROWKIS_TENANT", "demo"), auth_token=os.getenv("CROWKIS_TOKEN"))
    replay = ReplayUnderstander({"What is your return policy?": "policy"})
    session = CallSession(
        Agent("support", client=client, tenant=os.getenv("CROWKIS_TENANT", "demo")),
        WithFallback(LLMUnderstander(complete, business=BUSINESS), replay),
        replay=replay,
        on_urgent=lambda turn, frame: print("   !! URGENT: alert a human now"),
        understand_budget_ms=5000,      # a hosted LLM is slow; voice needs a fast local model
        latency_budget_ms=1000,
    )
    session.register_shape("eta", "Your order arrives on {eta}.", requires="identified")
    history = []

    print("Type as the caller (empty line to quit).")
    while True:
        said = input("caller> ").strip()
        if not said:
            break
        result = session.handle(said)
        print(f"   [{result.route}] {result.reason}" + (f"  key={result.verdict.key}" if result.verdict and
                                                        result.verdict.key else ""))
        history.append({"role": "user", "content": said})
        if result.text:                                     # cache hit or filler
            answer = result.text
        else:
            messages = result.messages if result.messages is not None else history
            answer = complete([SYSTEM] + messages)
            print("   " + session.record_answer(result, answer))
        history.append({"role": "assistant", "content": answer})
        print("agent> " + answer)
    print(json.dumps(session.stats(), indent=1))


if __name__ == "__main__":
    main()
