"""Scratch alias shim: old crowkis.<module> paths resolve to names found anywhere in v4 crowkis.*"""
import atexit, importlib, importlib.abc, importlib.machinery, json, os, pkgutil, sys, types

OLD = ["agent", "voice", "voice_async", "callstate", "chat", "session", "turn", "understand", "verify",
       "voice_turns", "openai_wrapper", "_config", "grpc_stub", "realtime", "grpc"]
RESOLVED, MISSING = {}, set()
_index = None

def _build():
    global _index
    if _index is not None:
        return _index
    import crowkis
    _index = {}
    mods = []
    for info in pkgutil.walk_packages(crowkis.__path__, "crowkis."):
        try:
            mods.append(importlib.import_module(info.name))
        except BaseException:
            pass
    for m in mods:
        for k, v in vars(m).items():
            if k.startswith("__"):
                continue
            _index.setdefault(k, []).append((m.__name__, v))
    return _index

def lookup(old, name):
    cands = _build().get(name)
    if not cands:
        MISSING.add((old, name))
        raise AttributeError(name)
    pick = next((c for c in cands if getattr(c[1], "__module__", None) == c[0]), cands[0])
    RESOLVED[(old, name)] = pick[0]
    return pick[1]

class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("crowkis.") and fullname[8:] in OLD:
            return importlib.machinery.ModuleSpec(fullname, self)
    def create_module(self, spec):
        m = types.ModuleType(spec.name)
        m.__getattr__ = lambda n, old=spec.name: lookup(old, n) if not n.startswith("__") else (_ for _ in ()).throw(AttributeError(n))
        return m
    def exec_module(self, module):
        pass

sys.meta_path.append(_Finder())  # appended: real v4 modules win

import crowkis, crowkis.client
def _fallback(old):
    def g(n):
        if n.startswith("__"):
            raise AttributeError(n)
        return lookup(old, n)
    return g
crowkis.client.__getattr__ = _fallback("crowkis.client")

@atexit.register
def _dump():
    out = os.environ.get("ALIAS_LOG")
    if out:
        with open(out, "w") as f:
            json.dump({"resolved": sorted(f"{a}.{b} -> {c}" for (a, b), c in RESOLVED.items()),
                       "missing": sorted(f"{a}.{b}" for a, b in MISSING)}, f, indent=1)
