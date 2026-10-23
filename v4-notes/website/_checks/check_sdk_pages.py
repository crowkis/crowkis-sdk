"""The Python SDK, Quickstart and Configuration pages' code, against a real server
(CROWKIS_* in the environment). Every name a page uses must exist; the core calls run."""
import asyncio
import inspect
import os
import random
import sys

import crowkis
from crowkis import AsyncCrowkis, Crowkis, CrowkisAdmin, CrowkisClient, CrowkisMemory

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


word = "".join(random.choice("bcdfghjklmnpqrstvwxz") + random.choice("aeiou") for _ in range(3))

# names the pages use
check("Crowkis is CrowkisClient", Crowkis is CrowkisClient)
for name in ("cached", "ask", "get_or_compute", "lookup", "store", "similar", "flush", "close"):
    check(f"Crowkis.{name} exists", hasattr(Crowkis, name))
check("AsyncCrowkis.stream exists", hasattr(AsyncCrowkis, "stream"))
for name in ("remember", "recall", "extract", "history", "forget", "link", "graph"):
    check(f"CrowkisMemory.{name} exists", hasattr(CrowkisMemory, name))
for name in ("get_stats", "health", "flush_tenant", "invalidate_source"):
    check(f"CrowkisAdmin.{name} exists", hasattr(CrowkisAdmin, name))
params = inspect.signature(CrowkisClient.__init__).parameters
check("Crowkis(host=, port=, tenant=, auth_token=, token=)", all(p in params for p in ("host", "port", "tenant", "auth_token", "token")))
check("crowkis.help exists", callable(getattr(crowkis, "help", None)))
for name in ("Chat", "LLMUnderstander", "Agent", "async_voice_session", "voice_session"):
    check(f"crowkis.{name} exists", hasattr(crowkis, name))

# the calls, against the server
cache = Crowkis()
calls = []


@cache.cached(ttl=3600)
def answer(prompt: str) -> str:
    calls.append(prompt)
    return f"The {word} plan costs nothing."


q = f"what does the {word} plan cost"
answer(q)
import time

time.sleep(1.5)
answer(q)
check("decorator: the second ask is served from the cache", len(calls) == 1, str(calls))
check("ask(compute=) answers", cache.ask(q, compute=lambda p: "x", ttl=3600) == f"The {word} plan costs nothing.")
cache.store(f"when does the {word} office open", "At nine.", ttl=3600)
time.sleep(1.5)
hit = cache.lookup(f"when does the {word} office open")
check("store then lookup", hit is not None and hit.text == "At nine.", repr(hit))
check("CacheHit has text, similarity, confidence", hit is not None and all(hasattr(hit, a) for a in ("text", "similarity", "confidence")))


async def stream():
    async with AsyncCrowkis() as c:
        async def my_stream(p):
            for piece in ["Vector ", "caches."]:
                yield piece
        return "".join([chunk if isinstance(chunk, str) else chunk.decode() async for chunk in
                        c.stream(f"explain {word} caches", compute=my_stream, ttl=3600)])


check("AsyncCrowkis().stream(compute=) streams", asyncio.run(stream()) == "Vector caches.")
cache.close()

admin = CrowkisAdmin("http://127.0.0.1:6384", token=os.environ["CROWKIS_AUTH_TOKEN"])
health = admin.health()
check("CrowkisAdmin on 6384: health()", bool(health), str(health)[:80])
print(f"{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
