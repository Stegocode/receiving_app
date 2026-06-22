# Contributing

## Branching

Branch off `main`. Keep each branch focused on one ticket. Do not commit
directly to `main`.

```bash
git fetch origin
git checkout -b my-feature origin/main
```

---

## Gate sequence

Every gate must be green before you commit. Run them in this order:

```bash
ruff check .
ruff format --check .
mypy core services adapters config.py
lint-imports
python scripts/conformance.py
pytest --cov=core --cov=services --cov=config --cov-fail-under=95 -q
```

Fix the code to satisfy each gate. Do not weaken a gate threshold or skip a
check to make a commit pass.

The pre-commit hook is the mechanical enforcer. If you need to commit with a
broken hook (e.g. hook tooling issue), use `--no-verify` and fix the gate
failure before merging.

---

## Conformance and banned terms

The conformance gate (`python scripts/conformance.py`) includes a banned-term
check (`gate_a`) that rejects client/vendor/operator names, real board/group
IDs, and real portal URLs from all tracked files.

The banned-term list lives in `.conformance-banned` (gitignored). In CI it is
provisioned from the `CONFORMANCE_BANNED` repository secret. Locally, create
`.conformance-banned` with one term per line, or the gate will skip `gate_a`
with a warning.

Do not include proprietary names, real IDs, or real URLs in any committed
file — this is a public repository.

---

## Commits and PRs

- Commit messages: `T-XX: short imperative description` — one line, present
  tense, no trailing period. Example: `T-17: tiered docs`.
- Open a PR against `main`. Do not self-merge. Request independent review.
- Version is canonical in `pyproject.toml`. Do not add a separate `VERSION`
  file.
- `DEBT.md` is the deferred-decision ledger. If your change defers something,
  add a dated entry. If your change resolves a debt item, mark it resolved.

---

## Live-untested adapters

Several adapters are ported and unit-tested with fakes but have not been
validated against live infrastructure. The current list is in `DEBT.md`.

When you add a new adapter that requires live systems to fully test, add a
`DEBT-Txx-nnn` entry to `DEBT.md` before merging. When you do validate a
live adapter, update the debt entry.

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/). The canonical
version is in `pyproject.toml` under `[project] version`. Update it when
tagging a release; do not add a separate `VERSION` file.
