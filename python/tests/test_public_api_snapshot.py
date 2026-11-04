"""Public API contract: every public name, method and keyword is pinned in fixtures/public-api.json (section "python").

A name in the snapshot that is gone now (removed or renamed) fails; a new public name fails too, so
adding to the API is a deliberate snapshot update. Regenerate (rewrites only the "python" section):
    CROWKIS_UPDATE_API_SNAPSHOT=1 python -m pytest -q -p no:cacheprovider tests/test_public_api_snapshot.py
"""
import inspect
import json
import os
from pathlib import Path

import crowkis
from crowkis import privacy

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "public-api.json"


def _params(thing):
    try:
        names = [p for p in inspect.signature(thing).parameters if p not in ("self", "cls")]
    except (TypeError, ValueError):
        return ""  # builtins without a signature
    return "(" + ", ".join(names) + ")"


def _describe(name, thing, out):
    if inspect.isclass(thing):
        out.append(name + _params(thing))
        for member, value in inspect.getmembers(thing):
            if member.startswith("_"):
                continue
            if isinstance(inspect.getattr_static(thing, member), property):
                out.append(f"{name}.{member}")
            elif callable(value):
                out.append(f"{name}.{member}{_params(value)}")
            else:
                out.append(f"{name}.{member}")
    elif callable(thing):
        out.append(name + _params(thing))
    else:
        out.append(name)


def current():
    root = sorted({n for n in vars(crowkis) if not n.startswith("_") and not inspect.ismodule(getattr(crowkis, n))}
                  | set(crowkis.__all__))
    shapes = []
    for name in root:
        _describe(name, getattr(crowkis, name), shapes)
    private = sorted(n for n in vars(privacy) if not n.startswith("_") and not inspect.ismodule(getattr(privacy, n)))
    shapes_privacy = []
    for name in private:
        _describe(name, getattr(privacy, name), shapes_privacy)
    return {"crowkis": root, "crowkis.privacy": private, "shapes": sorted(shapes),
            "shapes.privacy": sorted(shapes_privacy)}


def test_public_api_matches_the_snapshot():
    now = current()
    data = json.loads(FIXTURE.read_text("utf-8")) if FIXTURE.exists() else {}
    if os.environ.get("CROWKIS_UPDATE_API_SNAPSHOT") == "1":
        data["python"] = now
        FIXTURE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
        return
    snap = data["python"]
    problems = []
    for key in sorted(set(snap) | set(now)):
        gone = sorted(set(snap.get(key, [])) - set(now.get(key, [])))
        new = sorted(set(now.get(key, [])) - set(snap.get(key, [])))
        if gone:
            problems.append(f"python.{key}: missing now (removed or renamed): {gone}")
        if new:
            problems.append(f"python.{key}: new public name: update fixtures/public-api.json on purpose: {new}")
    assert not problems, "\n".join(problems)
