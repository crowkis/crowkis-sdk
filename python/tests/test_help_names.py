"""crowkis.help() names only things that can be imported from where it says."""
import importlib
import unittest

import crowkis


class HelpNameTests(unittest.TestCase):
    def test_the_openai_wrapper_is_named_where_it_lives(self):
        text = crowkis.help_text()
        self.assertIn("crowkis.integrations.openai.CachedOpenAI", text)
        self.assertNotIn("crowkis.CachedOpenAI", text.replace("crowkis.integrations.openai.CachedOpenAI", ""))
        self.assertTrue(hasattr(importlib.import_module("crowkis.integrations.openai"), "CachedOpenAI"))


if __name__ == "__main__":
    unittest.main()
