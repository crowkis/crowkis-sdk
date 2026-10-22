"""Compares today's decisions with the golden files, field by field, and lists what differs.

For a refactor step that adds a field (``stats()["rules"]`` in v4 P1): every difference must
be in the fields named with ``--added`` and nothing else. Run from python/:
``python tests/golden/compare.py --added stats.rules``. Exit code 1 when anything else differs.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterator, List, Set, Tuple

from replay import ChatReplay, VoiceReplay, golden_path, replay, suites


ABSENT = "<absent>"


def differences(expected: Any, actual: Any, where: Tuple = ()) -> Iterator[Tuple[Tuple, Any, Any]]:
    """Every (path, expected, actual) that differs; a path is the tuple of keys and list indexes."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            yield from differences(expected.get(key, ABSENT), actual.get(key, ABSENT), where + (key,))
    elif isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        for index, (left, right) in enumerate(zip(expected, actual)):
            yield from differences(left, right, where + (index,))
    elif expected != actual:
        yield where, expected, actual


def field_of(path: Tuple) -> str:
    """The field a path ends in, without the call: ("calls", "A01", "stats", "rules") -> "stats.rules"."""
    rest = path[2:] if len(path) > 2 and path[0] == "calls" else path
    return ".".join(str(part) for part in rest)


def main(added: Set[str]) -> int:
    unexpected: List[str] = []
    for pipeline in (VoiceReplay(), ChatReplay()):
        for suite, calls in suites().items():
            expected = json.loads(golden_path(pipeline.pipeline, suite).read_text("utf-8"))
            actual = json.loads(json.dumps(replay(pipeline, calls)))
            for path, before, after in differences(expected, actual):
                if field_of(path) not in added:
                    unexpected.append(f"{pipeline.pipeline}/{suite} {path}: {before!r} -> {after!r}")
    for line in unexpected[:40]:
        print(line)
    print(f"{len(unexpected)} difference(s) outside {sorted(added)}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--added", action="append", default=[])
    sys.exit(main(set(parser.parse_args().added)))
