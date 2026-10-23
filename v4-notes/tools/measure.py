"""P5.5 measures for one exported tree: cognitive complexity, function and file lengths, forward-only classes.

Usage: measure-venv python measure.py <tree root> <label>   (tree root holds python/ and node/)
Prints a Markdown summary; writes <label>.json next to this script with the per-function detail."""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
LABEL = sys.argv[2]
HERE = Path(__file__).parent
PY_DIRS = ["turns", "rules", "runtime", "understanding", "state", "keys", "transport", "channels", "integrations"]
PY = [p for d in PY_DIRS for p in sorted((ROOT / "python" / "crowkis" / d).rglob("*.py"))] + \
     [p for p in sorted((ROOT / "python" / "crowkis").glob("*.py")) if p.name not in ("client.py", "grpc_stub.py")]
JS = sorted((ROOT / "node" / "src").rglob("*.js"))
LIZARD = [str(HERE / "measure-venv" / "Scripts" / "python.exe"), "-m", "lizard", "--csv"]


def lizard(paths):
    out = subprocess.run(LIZARD + [str(p) for p in paths], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    rows = []
    for line in out.splitlines():
        cells = next(iter(__import__("csv").reader([line])))
        if len(cells) >= 8 and cells[0].isdigit():
            rows.append({"nloc": int(cells[0]), "ccn": int(cells[1]), "file": cells[6], "function": cells[7]})
    return rows


def python_cognitive(paths):
    from complexipy import file_complexity  # noqa: PLC0415
    found = []
    for path in paths:
        try:
            result = file_complexity(str(path))
        except Exception:  # noqa: BLE001
            continue
        for fn in result.functions:
            found.append({"file": str(path), "function": fn.name, "cognitive": fn.complexity})
    return found


def js_cognitive(paths):
    eslint = HERE / "measure-js" / "node_modules" / "eslint" / "bin" / "eslint.js"
    config = HERE / "measure-js" / ".eslintrc.json"
    config.write_text(json.dumps({"root": True, "parserOptions": {"ecmaVersion": 2022, "sourceType": "script"},
                                  "plugins": ["sonarjs"], "rules": {"sonarjs/cognitive-complexity": ["error", 0]}}))
    out = subprocess.run(["node", str(eslint), "--no-eslintrc", "-c", str(config), "--resolve-plugins-relative-to",
                          str(HERE / "measure-js"), "-f", "json"] + [str(p) for p in paths],
                         capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL).stdout
    found = []
    for result in json.loads(out or "[]"):
        for message in result["messages"]:
            m = re.search(r"from (\d+) to", message.get("message", ""))
            if m:
                found.append({"file": result["filePath"], "line": message["line"], "cognitive": int(m.group(1))})
    return found


def forward_only_python(paths):
    """Classes whose every method (besides __init__) is one statement handing the call to an attribute of self."""
    found = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            methods = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name != "__init__"]
            def forwards(m):
                body = [s for s in m.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
                if len(body) != 1 or not isinstance(body[0], (ast.Return, ast.Expr)) or body[0].value is None:
                    return False
                call = body[0].value
                return isinstance(call, (ast.Call, ast.Attribute)) and "self._" in ast.unparse(call)
            if len(methods) >= 3 and sum(forwards(m) for m in methods) >= 0.8 * len(methods):
                found.append(f"{path.relative_to(ROOT)}:{cls.name}")
    return found


def lines(paths):
    return {str(p.relative_to(ROOT)): sum(1 for _ in p.open(encoding="utf-8")) for p in paths}


def summary(name, fn_rows, cog_rows, file_lengths):
    nloc = [r["nloc"] for r in fn_rows]
    cog = [r["cognitive"] for r in cog_rows]
    return {
        "language": name, "files": len(file_lengths), "functions": len(nloc),
        "cognitive_max": max(cog, default=0), "cognitive_mean_reported": round(sum(cog) / len(cog), 2) if cog else 0,
        "cognitive_over_15": sum(c > 15 for c in cog), "function_nloc_max": max(nloc, default=0),
        "function_nloc_mean": round(sum(nloc) / len(nloc), 2) if nloc else 0, "functions_over_20_lines": sum(n > 20 for n in nloc),
        "file_lines_max": max(file_lengths.values(), default=0), "files_over_300_lines": sum(v > 300 for v in file_lengths.values()),
        "cyclomatic_max": max((r["ccn"] for r in fn_rows), default=0),
    }


py_fn, js_fn = lizard(PY), lizard(JS)
py_cog, js_cog = python_cognitive(PY), js_cognitive(JS)
report = {
    "python": summary("python", py_fn, py_cog, lines(PY)),
    "node": summary("node", js_fn, js_cog, lines(JS)),
    "forward_only_python": forward_only_python(PY),
    "worst_cognitive_python": sorted(py_cog, key=lambda r: -r["cognitive"])[:10],
    "worst_cognitive_node": sorted(js_cog, key=lambda r: -r["cognitive"])[:10],
    "longest_files": sorted(list(lines(PY).items()) + list(lines(JS).items()), key=lambda kv: -kv[1])[:10],
}
(HERE / f"{LABEL}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
for lang in ("python", "node"):
    print(lang, json.dumps(report[lang]))
print("forward-only (python):", len(report["forward_only_python"]), report["forward_only_python"][:8])
print("worst cognitive (python):", [(Path(r["file"]).name, r["function"], r["cognitive"]) for r in report["worst_cognitive_python"][:5]])
print("worst cognitive (node):", [(Path(r["file"]).name, r["line"], r["cognitive"]) for r in report["worst_cognitive_node"][:5]])
print("longest files:", report["longest_files"][:6])
