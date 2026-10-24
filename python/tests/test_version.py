"""crowkis.__version__ is the package's version, the same as pyproject.toml and the Node
package (@crowkis/client), so a bug report can say which SDK it came from."""
import json
import re
import unittest
from pathlib import Path

import crowkis

ROOT = Path(__file__).resolve().parents[2]


class VersionTests(unittest.TestCase):
    def test_the_version_matches_pyproject_and_the_node_package(self):
        pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "python" / "pyproject.toml").read_text("utf-8"), re.M)
        node = json.loads((ROOT / "node" / "package.json").read_text("utf-8"))["version"]
        self.assertEqual(crowkis.__version__, pyproject.group(1))
        self.assertEqual(crowkis.__version__, node)

    def test_it_is_listed_with_the_package_exports(self):
        self.assertIn("__version__", crowkis.__all__)
        self.assertRegex(crowkis.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
