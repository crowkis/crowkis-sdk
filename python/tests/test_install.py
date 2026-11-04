"""Clean install: build the wheel and sdist, install into a fresh venv, import everything.

Slow (builds and installs, needs network once for setuptools), so only with CROWKIS_SLOW_TESTS=1.
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[1]
PROTO = "crowkis/client/grpc/crowkis.proto"

# Run inside the installed venv, from a neutral cwd.
PROBE = r"""
import importlib, json, pkgutil, crowkis, crowkis.privacy
names = {n: hasattr(crowkis, n) for n in crowkis.__all__}
imported, optional_missing = [], {}
for info in pkgutil.walk_packages(crowkis.__path__, "crowkis."):
    try:
        importlib.import_module(info.name)
        imported.append(info.name)
    except ImportError as error:
        if ".integrations." not in info.name and not info.name.endswith(".integrations"):
            raise
        optional_missing[info.name] = str(error)
print(json.dumps({"file": crowkis.__file__, "names": names, "imported": imported,
                  "optional_missing": optional_missing}))
"""


def make_venv(path):
    venv.EnvBuilder(with_pip=True).create(path)
    return Path(path) / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def run(args, **kwargs):
    done = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if done.returncode:
        raise AssertionError(f"{args[:3]} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


@unittest.skipUnless(os.environ.get("CROWKIS_SLOW_TESTS") == "1", "slow test: set CROWKIS_SLOW_TESTS=1")
class CleanInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="crowkis-install-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        # Build from a copy so the repo gets no build/ or egg-info folders.
        source = cls.tmp / "src"
        source.mkdir()
        for name in ("pyproject.toml", "README.md"):
            shutil.copy(PYTHON_DIR / name, source / name)
        shutil.copytree(PYTHON_DIR / "crowkis", source / "crowkis", ignore=shutil.ignore_patterns("__pycache__"))
        builder = make_venv(cls.tmp / "build-venv")
        try:
            run([builder, "-m", "pip", "install", "-q", "setuptools>=68"])
        except AssertionError as error:
            raise unittest.SkipTest(f"setuptools could not be installed (offline?): {error}")
        cls.dist = cls.tmp / "dist"
        cls.dist.mkdir()
        for call in ("build_wheel", "build_sdist"):
            run([builder, "-c", f"from setuptools import build_meta as b; b.{call}({str(cls.dist)!r})"], cwd=source)
        cls.wheel = next(cls.dist.glob("*.whl"))
        cls.sdist = next(cls.dist.glob("*.tar.gz"))

    def probe(self, installer_args, name):
        python = make_venv(self.tmp / name)
        run([python, "-m", "pip", "install", "-q", *installer_args])
        elsewhere = self.tmp / (name + "-cwd")
        elsewhere.mkdir()
        # -I: ignore the cwd and PYTHONPATH, so only the installed copy can be imported.
        out = run([python, "-I", "-c", PROBE], cwd=elsewhere, env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
        result = json.loads(out.strip().splitlines()[-1])
        self.assertTrue(Path(result["file"]).resolve().is_relative_to((self.tmp / name).resolve()), result["file"])
        return python, result

    def check_imports(self, result):
        self.assertTrue(result["names"], "empty __all__")
        self.assertEqual([n for n, ok in result["names"].items() if not ok], [])
        for needed in ("crowkis.privacy", "crowkis.client", "crowkis.turns", "crowkis.rules", "crowkis.runtime"):
            self.assertIn(needed, result["imported"])
        print("optional integrations not importable here:", sorted(result["optional_missing"]))

    def test_wheel_installs_and_imports_everything(self):
        with zipfile.ZipFile(self.wheel) as wheel:
            members = wheel.namelist()
        self.assertIn(PROTO, members)
        python, result = self.probe([self.wheel], "wheel-venv")
        self.check_imports(result)
        site = run([python, "-I", "-c", "import crowkis,pathlib;print(pathlib.Path(crowkis.__file__).parent)"])
        self.assertTrue((Path(site.strip()) / "client" / "grpc" / "crowkis.proto").is_file())

    def test_sdist_holds_everything_the_wheel_has_and_installs(self):
        with zipfile.ZipFile(self.wheel) as wheel:
            wanted = {n for n in wheel.namelist() if n.endswith((".py", ".proto"))}
        with tarfile.open(self.sdist) as sdist:
            held = {n.split("/", 1)[1] for n in sdist.getnames() if "/" in n}
        self.assertEqual(sorted(wanted - held), [])
        _, result = self.probe([self.sdist], "sdist-venv")
        self.check_imports(result)


if __name__ == "__main__":
    unittest.main()
