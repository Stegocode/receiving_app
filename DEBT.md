# DEBT

Tracked decisions deferred in this build. Each entry states what was deferred,
why, and the signal that should trigger resolving it.

---

[DEBT-T01] 2026-06-17 — Skeleton only, no logic.
All .py files in this commit are stubs. Business logic, port implementations,
and tests are implemented in T-02 through T-14.

[DEBT-CI01] 2026-06-17 — No entry-point smoke test; `python -m receiving_app` retired.
Deferred: a CI gate that launches the app and asserts a clean exit. Fixing flat-layout
package discovery required deleting the root `receiving_app` package, which retired the
original `python -m receiving_app` command — the app now starts via `python __main__.py`,
and no gate proves it starts at all. Resolve in T-02: declare a canonical entry point
([project.scripts]) and add a gate that runs it and asserts exit 0. Trigger: T-02, or the
first ticket that touches startup/config wiring, whichever comes first.
