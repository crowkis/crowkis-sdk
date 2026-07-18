"""LlamaIndex-style get_or_compute example for Crowkis."""

from crowkis import CrowkisClient


cache = CrowkisClient(tenant="llamaindex-demo", model="gpt-4o")


def query_with_cache(prompt: str, query_engine) -> str:
    return cache.get_or_compute(
        prompt,
        lambda q: str(query_engine.query(q)),
        threshold=0.88,
        ttl=3600,
    )
