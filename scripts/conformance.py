#!/usr/bin/env python3
"""
Conformance gates — run with: python scripts/conformance.py

Owns: mechanical enforcement of all build-constitution rules across tracked files.
Must not: modify any source file; must not perform network calls.
May import: ast, re, subprocess, sys, pathlib (stdlib only).
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

FAILURES = []


def fail(gate, msg):
    FAILURES.append(f"[{gate}] {msg}")


def tracked_files():
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT)
    return [Path(p) for p in result.stdout.splitlines() if p]


def read(path):
    try:
        return (ROOT / path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


# ── a. Banned names ───────────────────────────────────────────────────────────
# Runtime "+" concatenation keeps the banned strings out of this source file.
_ALWAYS_BANNED = [
    "Bas" + "co",  # client name
    "scott" + "t",  # operator username
    "Home" + "Source",  # vendor name — use adapters/source.py
    "Mon" + "day",  # vendor name — use adapters/sink.py
]


def banned_name_hit(name: str, text: str, path: str) -> bool:
    """Return True if *name* appears (case-insensitively) in *text* or *path*."""
    needle = name.lower()
    return needle in text.lower() or needle in path.lower()


def gate_a(files):
    for f in files:
        text = read(f)
        norm = str(f).replace("\\", "/")
        for name in _ALWAYS_BANNED:
            if banned_name_hit(name, text, norm):
                fail("a", f"{norm}: contains banned name '{name}'")


# ── b. Absolute paths ─────────────────────────────────────────────────────────
# Patterns are assembled so the literals don't appear in this source file.
_ABS_PATTERNS = [
    "C:" + chr(92),  # Windows backslash-style drive path
    "C" + ":/",  # Windows forward-slash-style drive path
    "/" + "Users" + "/",  # macOS home-directory path
    "/" + "home" + "/",  # Linux home-directory path
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


# ── l. No string-built SQL ────────────────────────────────────────────────────
# Constitution 4: fail closed — no dynamic query construction.
_SQL_KW = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


def _sql_in_fstring(node):
    """Return True if a JoinedStr contains a SQL keyword in any constant part."""
    for part in ast.walk(node):
        if (
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and _SQL_KW.search(part.value)
        ):
            return True
    return False


def gate_l(files):
    for f in files:
        if not str(f).endswith(".py"):
            continue
        src = read(f)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        norm = str(f).replace("\\", "/")
        for node in ast.walk(tree):
            # f-string with SQL keyword
            if isinstance(node, ast.JoinedStr) and _sql_in_fstring(node):
                fail("l", f"{norm}: f-string contains SQL keyword (use parameterised queries)")
                break
            # "SELECT ..." % (...) or "SELECT ..." + ...
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Mod | ast.Add)
                and isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, str)
                and _SQL_KW.search(node.left.value)
            ):
                fail(
                    "l",
                    f"{norm}: %-format or +-concat with SQL keyword (use parameterised queries)",
                )
                break
            # "SELECT ...".format(...)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and isinstance(node.func.value, ast.Constant)
                and isinstance(node.func.value.value, str)
                and _SQL_KW.search(node.func.value.value)
            ):
                fail("l", f"{norm}: .format() on SQL string (use parameterised queries)")
                break


# ── m. No Match-Not-Found-Error ───────────────────────────────────────────────
# Spec: matching returns a status enum, never raises.
_MATCH_NOT_FOUND = "Match" + "NotFoundError"


def gate_m(files):
    for f in files:
        if not str(f).endswith(".py"):
            continue
        if _MATCH_NOT_FOUND in read(f):
            norm = str(f).replace(chr(92), "/")
            fail(
                "m",
                norm
                + ": contains "
                + _MATCH_NOT_FOUND
                + " (matching returns a status, never raises)",
            )


# ── n. No input() in services/ ────────────────────────────────────────────────
# IO belongs at adapters, not services. AST walk avoids false positives from
# boundary-header docstrings that mention the prohibition by name.
def gate_n(files):
    for f in files:
        norm = str(f).replace("\\", "/")
        if not norm.startswith("services/") or not norm.endswith(".py"):
            continue
        src = read(f)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "input"
            ):
                fail("n", f"{norm}: input() in services/ (IO belongs at adapters)")
                break


# ── o. No module-level telemetry global ───────────────────────────────────────
# Module 05: metrics are injected, never singletons.
_IMPORT_TELEMETRY = "import" + " telemetry"
_CORE_TELEMETRY = "core" + ".telemetry"


def gate_o(files):
    for f in files:
        if not str(f).endswith(".py"):
            continue
        text = read(f)
        norm = str(f).replace("\\", "/")
        if _IMPORT_TELEMETRY in text or _CORE_TELEMETRY in text:
            fail("o", f"{norm}: contains telemetry import (metrics injected, not singletons)")
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "telemetry":
                        fail(
                            "o",
                            f"{norm}: module-level `telemetry =`"
                            " (metrics injected, not singletons)",
                        )
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "telemetry"
            ):
                fail("o", f"{norm}: module-level `telemetry =` (metrics injected, not singletons)")


# ── main ──────────────────────────────────────────────────────────────────────
GATES = [
    gate_a,
    gate_b,
    gate_c,
    gate_d,
    gate_e,
    gate_g,
    gate_h,
    gate_i,
    gate_j,
    gate_k,
    gate_l,
    gate_m,
    gate_n,
    gate_o,
]


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
