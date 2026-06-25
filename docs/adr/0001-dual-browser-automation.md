# ADR 0001 — Dual Browser Automation Libraries

**Status:** Accepted

---

## Context

An architecture review (issue #33 / #35 item 5) suggested consolidating the two
browser-automation libraries — Selenium and Playwright — down to one, to reduce
maintenance surface.

The codebase contains two distinct programs that each drive a browser:

| Program | Purpose | Library |
|---------|---------|---------|
| Source / `populate` adapter | Scrapes the vendor portal catalog to build the local item database | Selenium |
| Receiver / `robot` adapter | Drives the receiving-platform wizard to submit purchase orders | Playwright |

These programs run independently and serve different subsystems.

---

## Decision

**Keep both libraries.**

Selenium and Playwright are not interchangeable for these two use cases.
The receiver automation relies on Playwright-specific behaviour (async page
model, network interception, reliable waiting strategies for the target
wizard) and cannot be re-implemented in Selenium without functional loss.
The source scrape was built on and continues to work correctly with Selenium.

Consolidating to a single library would require rewriting at least one
adapter and would risk regressions in a subsystem the replacement library
was not designed for.

**Secondary benefit — failure isolation.** Because the two programs have
separate stacks, a browser-automation failure is immediately attributable:
it either broke in `populate` (source / Selenium) or in `robot`
(receiver / Playwright). Mixed-stack failures are unambiguous; a
single-library consolidation would obscure that boundary.

---

## Consequences

* Two browser-automation dependencies (`selenium`, `playwright`) are
  maintained intentionally and permanently in this repository.
* The standard for this repo — and as a template for other adapter-pattern
  apps — is **"use the library the automation requires,"** not "one library
  everywhere."
* This ADR exists so the dual-stack choice is not repeatedly re-flagged as
  accidental inconsistency during future architecture reviews.
* Reviewers who surface the consolidation suggestion again should be pointed
  here; no further discussion is needed unless the underlying automation
  requirements change.
