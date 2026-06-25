# docs/images

This directory holds screenshots and diagrams for the project documentation.
No images are committed to the repository yet — the placeholders below describe
what each file should show and how to produce it.

When adding an image, drop the file here and update the corresponding
`docs/*.md` or `README.md` file to reference it as
`![Alt text](docs/images/<filename>)`.

---

## Planned visuals

### `scanner-desk-idle.png`
**What to show:** the scanner desk UI (`receiving-app`) in its initial IDLE
state immediately after launch — the PO field empty, status panel blank.

**How to capture:** launch `receiving-app` in fake/manual mode
(`SOURCE_TYPE=fake SCANNER_TYPE=manual SINK_TYPE=null PRINTER_TYPE=preview`),
take a screenshot before entering any input.

---

### `scanner-desk-match.png`
**What to show:** the scanner desk after a successful scan — green flash state,
the status panel showing `received` with model number and serial filled in.

**How to capture:** with the fake adapter set active, load a PO (`PO:10001`),
enter a model number, then enter a matching serial. Screenshot immediately after
the green flash appears.

---

### `scanner-desk-no-match.png`
**What to show:** the scanner desk after a failed scan — red flash state, status
panel showing `no_match`.

**How to capture:** same fake setup as above, but enter a model string that does
not appear in the fixture data. Screenshot the red flash state.

---

### `architecture-layers.png`
**What to show:** the three-layer architecture diagram — core (innermost),
services (middle), adapters (outer) — with labelled arrows showing the
inward-only dependency direction.

**How to produce:** reproduce the ASCII diagram from `docs/FOR_DEVELOPERS.md`
as a clean vector or raster graphic. No tool-specific styling required.

---

### `daily-sequence.png`
**What to show:** a simple flowchart of the daily operator start sequence:
(1) run `receiving-refresh` → verify count → (2) start scanner and/or robot.

**How to produce:** a two-step flowchart with a decision branch for
"count looks right?" (yes → proceed, no → investigate).

---

### `board-groups-flow.png`
**What to show:** how items move between board groups. Starting state: READY.
Success path: READY → RECEIVED. Failure paths: READY → NO MATCH, READY →
ATTENTION.

**How to produce:** a state diagram with four nodes (READY, RECEIVED, NO MATCH,
ATTENTION) and labelled transition arrows (robot receives successfully; no match
/ missing fields; needs attention signal).

---

### `robot-pass-flow.png`
**What to show:** the robot's per-pass decision tree. Starting from "poll READY
group": for each item → validate fields (missing → NO MATCH) → drive wizard →
success (→ RECEIVED) / no-match / error (stay in READY, retry next pass) →
check circuit breaker threshold → sleep → repeat.

**How to produce:** a flowchart with the circuit-breaker check (< 50 % success
after ≥ 5 attempts → KILL) shown as a branch after the pass summary.

---

## Contribution notes

- Prefer PNG for screenshots; SVG for diagrams.
- Keep file sizes reasonable — compress screenshots if over 500 KB.
- Use generic labels in diagrams (e.g. "purchase order portal", "result board").
  Do not embed proprietary product names, real URLs, or customer-specific labels
  in committed image files.
- Update this file when adding a new visual or removing a placeholder.
