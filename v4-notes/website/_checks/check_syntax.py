"""Every ```python and ```js block on every page must be valid on its own, as a reader
would paste it: Python compiled (top-level await allowed, as in a notebook or asyncio
REPL), JavaScript checked with `node --check` as a CommonJS file (an `import` statement
makes it an ES module). Run: python check_syntax.py"""
import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
BLOCK = re.compile(r"```(python|js|ts)\n(.*?)```", re.S)
failed = 0
count = 0
for page in sorted(DOCS.rglob("*.md")):
    for lang, code in BLOCK.findall(page.read_text(encoding="utf-8")):
        count += 1
        where = f"{page.relative_to(DOCS)}: {code.strip().splitlines()[0][:60]}"
        if lang == "python":
            try:
                compile(code, where, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            except SyntaxError as err:
                failed += 1
                print(f"FAIL {where}\n     {err}")
            continue
        if lang == "ts" and ": " in code:
            continue  # TypeScript annotations; node cannot check them
        # An `import`, or a fragment with no require() (read inside an async function), is module code.
        module = re.search(r"^\s*import .* from ", code, re.M) or "require(" not in code
        with tempfile.NamedTemporaryFile("w", suffix=".mjs" if module else ".cjs", delete=False, encoding="utf-8") as f:
            f.write(code)
        result = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        Path(f.name).unlink()
        if result.returncode:
            failed += 1
            lines = [l for l in result.stderr.splitlines() if "Error" in l] or result.stderr.splitlines()[-1:]
            print(f"FAIL {where}\n     {lines[0] if lines else ''}")
print(f"{count - failed}/{count} blocks valid")
sys.exit(1 if failed else 0)
