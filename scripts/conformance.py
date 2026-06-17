#!/usr/bin/env python3
"""Conformance gates — run with: python scripts/conformance.py"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

FAILURES = []


def fail(gate, msg):
    FAILURES.append(f"[{gate}] {msg}")


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT
    )
    return [Path(p) for p in result.stdout.splitlines() if p]


def read(path):
    try:
        return (ROOT / path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


# ── a. Banned names ───────────────────────────────────────────────────────────
# Adjacent literals avoid the banned strings appearing literally in this file.
_ALWAYS_BANNED = [
    "Bas" "co",        # client name
    "scott" "t",       # operator username
]
_RESTRICTED = {
    "Home" "Source": "adapters/homesource.py",
    "Mon" "day": "adapters/monday.py",
}


def gate_a(files):
    for f in files:
        text = read(f)
        norm = str(f).replace("\\", "/")
        for name in _ALWAYS_BANNED:
            if name in text:
                fail("a", f"{norm}: contains banned name '{name}'")
        for name, allowed in _RESTRICTED.items():
            if name in text and norm != allowed:
                fail("a", f"{norm}: '{name}' only allowed in {allowed}")


# ── b. Absolute paths ─────────────────────────────────────────────────────────
# Patterns are assembled so the literals don't appear in this source file.
_ABS_PATTERNS = [
    "C:" + chr(92),         # Windows backslash-style drive path
    "C" + ":/",             # Windows forward-slash-style drive path
    "/" + "Users" + "/",    # macOS home-directory path
    "/" + "home" + "/",     # Linux home-directory path
]


def gate_b(files):
    for f in files:
        text = read(f)
        norm = str(f).replace("\\", "/")
        for p in _ABS_PATTERNS:
            if p in text:
                fail("b", f"{norm}: contains absolute path")


# ── c. Boundary headers ───────────────────────────────────────────────────────
_BOUNDARY_DIRS = {"core", "services", "adapters"}
_BOUNDARY_MARKERS = ("Owns:", "Must not:", "May import:")


def gate_c(files):
    for f in files:
        parts = Path(f).parts
        if not parts or parts[0] not in _BOUNDARY_DIRS:
            continue
        if not str(f).endswith(".py"):
            continue
        text = read(f)
        for marker in _BOUNDARY_MARKERS:
            if marker not in text:
                fail("c", f"{f}: missing boundary marker '{marker}'")


# ── d. Config isolation ───────────────────────────────────────────────────────
_ENV_READS = (
    "os." + "environ",
    "os." + "getenv",
    "environ" + ".get",
)


def gate_d(files):
    for f in files:
        if not str(f).endswith(".py"):
            continue
        norm = str(f).replace("\\", "/")
        if norm == "config.py":
            continue
        text = read(f)
        for pattern in _ENV_READS:
            if pattern in text:
                fail("d", f"{norm}: env read '{pattern}' outside config.py")


# ── e. File size ──────────────────────────────────────────────────────────────
_FILE_LINE_LIMIT = 400


def gate_e(files):
    for f in files:
        if not str(f).endswith(".py"):
            continue
        lines = read(f).splitlines()
        if len(lines) > _FILE_LINE_LIMIT:
            fail("e", f"{f}: {len(lines)} lines (limit {_FILE_LINE_LIMIT})")


# ── f. Function size ──────────────────────────────────────────────────────────
_FN_LINE_LIMIT = 60


def gate_f(files):
    for f in files:
        if not str(f).endswith(".py"):
            continue
        src = read(f)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno
                end = node.end_lineno or start
                length = end - start + 1
                if length > _FN_LINE_LIMIT:
                    fail(
                        "f",
                        f"{f}:{start}: '{node.name}' is {length} lines"
                        f" (limit {_FN_LINE_LIMIT})",
                    )


# ── g. Schema version ─────────────────────────────────────────────────────────
def gate_g(files):
    text = read(Path("core") / "schema.py")
    if "SCHEMA_VERSION" not in text:
        fail("g", "core/schema.py: SCHEMA_VERSION not declared")


# ── h. Debt ledger ────────────────────────────────────────────────────────────
def gate_h(_):
    debt = ROOT / "DEBT.md"
    if not debt.exists():
        fail("h", "DEBT.md does not exist")
    elif not debt.read_text(encoding="utf-8").strip():
        fail("h", "DEBT.md is empty")


# ── i. .env.example committed ─────────────────────────────────────────────────
def gate_i(files):
    tracked = {str(f).replace("\\", "/") for f in files}
    if ".env.example" not in tracked:
        fail("i", ".env.example is not a tracked git file")


# ── j. .env gitignored ────────────────────────────────────────────────────────
def gate_j(_):
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        fail("j", ".gitignore does not exist")
        return
    if ".env" not in gitignore.read_text(encoding="utf-8"):
        fail("j", ".gitignore does not contain .env")


# ── k. No __pycache__ tracked ─────────────────────────────────────────────────
def gate_k(files):
    for f in files:
        if "__pycache__" in str(f):
            fail("k", f"__pycache__ file is tracked: {f}")


# ── main ──────────────────────────────────────────────────────────────────────
GATES = [gate_a, gate_b, gate_c, gate_d, gate_e, gate_f, gate_g, gate_h, gate_i, gate_j, gate_k]


def main():
    files = tracked_files()
    for gate in GATES:
        gate(files)

    if FAILURES:
        print(f"\nConformance FAILED — {len(FAILURES)} violation(s):\n")
        for msg in FAILURES:
            print(f"  {msg}")
        sys.exit(1)

    print(f"Conformance OK — {len(GATES)} gates passed ({len(files)} tracked files)")


if __name__ == "__main__":
    main()
