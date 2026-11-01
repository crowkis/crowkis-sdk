"""v4 P5.6: the public, stable names apps and the outside scripts import (they never move with the internals)."""
import unittest

import crowkis
from crowkis import privacy


class PublicNameTests(unittest.TestCase):
    def test_the_routes_are_at_the_root(self):
        self.assertEqual((crowkis.AGENT, crowkis.PERSONAL, crowkis.SHARED, crowkis.TASK, crowkis.TOOLS, crowkis.URGENT,
                          crowkis.FILLER), ("agent", "personal", "shared", "task", "tools", "urgent", "filler"))

    def test_the_privacy_word_rules_have_public_names(self):
        self.assertTrue(privacy.is_personal("where is my order 48213"))
        self.assertTrue(privacy.is_context_dependent("and how long will that take"))
        self.assertFalse(privacy.is_context_dependent("what is your refund policy"))
        shape = privacy.abstract("Your order 48213 ships today.", {"order": "48213"})
        self.assertEqual(shape, "Your order {order} ships today.")
        self.assertFalse(privacy.leaks(shape, {"order": "48213"}))
        self.assertEqual(privacy.fill(shape, {"order": "77"}), "Your order 77 ships today.")
        self.assertTrue(privacy.SLOT.search(shape))
        self.assertGreater(privacy.CONTEXT_BOUND_THRESHOLD, 0.9)


if __name__ == "__main__":
    unittest.main()


class TypeHintTests(unittest.TestCase):
    """V4-4: an app that builds a typed model from a public class (FastAPI, pydantic) must not hit a NameError."""

    def test_every_public_class_resolves_its_type_hints(self):
        import inspect
        import typing

        import crowkis

        for name in crowkis.__all__:
            thing = getattr(crowkis, name)
            if inspect.isclass(thing):
                with self.subTest(name=name):
                    typing.get_type_hints(thing)
