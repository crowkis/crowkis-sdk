"""A cached answer streamed back in chunks reads exactly as it was stored (X1).

Node: test-stream-spacing.js.
"""
import asyncio
import unittest

from crowkis import AsyncCrowkis

ANSWERS = [
    "It waters at dawn for ten minutes.",
    "One two three four five six seven eight nine.",
    "Line one.\nLine two has   three spaces.\n\nA new paragraph.",
    "  Leading and trailing spaces.  ",
    "Short.",
    "हमारा स्टोर सुबह नौ बजे से शाम पांच बजे तक खुला रहता है।",
    "Aapka refund 5–7 business days mein aa jayega, sir ji.",
]


def _streamed(answer: str, **options) -> list:
    async def run():
        cache = AsyncCrowkis()

        async def cached(*args, **kwargs):
            return answer.encode("utf-8")

        cache.cget_async = cached

        async def never(prompt):
            raise AssertionError("a cache hit never calls the model")

        return [chunk async for chunk in cache.stream("q", compute=never, delay_ms=0, **options)]

    return asyncio.run(run())


class StreamSpacingTests(unittest.TestCase):
    def test_the_chunks_join_back_to_the_cached_answer(self):
        for answer in ANSWERS:
            for chunk_tokens in (1, 2, 4, 128):
                with self.subTest(answer=answer, chunk_tokens=chunk_tokens):
                    self.assertEqual("".join(_streamed(answer, chunk_tokens=chunk_tokens)), answer)

    def test_a_hit_still_streams_in_several_chunks(self):
        chunks = _streamed("It waters at dawn for ten minutes.")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].strip(), "It waters at dawn")

    def test_an_answer_of_only_spaces_streams_nothing(self):
        self.assertEqual(_streamed("   "), [])


if __name__ == "__main__":
    unittest.main()
