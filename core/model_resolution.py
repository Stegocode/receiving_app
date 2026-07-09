"""
Owns: tiered model-scan resolver (LEARNED → EXACT → WALK → NEEDS_MODEL).
Must not: perform I/O; must not import adapters or services.
May import: stdlib (dataclasses, enum), core.matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.matching import MatchStatus, resolve_exact, resolve_model


class ScanVerdict(Enum):
    AUTO = "auto"  # resolved; proceed to serial scan immediately
    PROPOSE = "propose"  # one walk candidate; block until operator confirms
    NEEDS_MODEL = "needs_model"  # unresolved; block until operator types model


@dataclass(frozen=True)
class ModelScanResult:
    """Typed result of the 4-step model-scan tiered resolver.

    AUTO:         model is set; proceed to serial scan immediately.
    PROPOSE:      model is the walk candidate; operator must re-scan the same
                  barcode to confirm (turnstile). scanner is blocked until then.
    NEEDS_MODEL:  model is None; operator must type the model. scanner is blocked.
    """

    verdict: ScanVerdict
    model: str | None  # set for AUTO and PROPOSE; None for NEEDS_MODEL


def resolve_scan(
    raw_barcode: str,
    po_models: list[str],
    learned_model: str | None,
) -> ModelScanResult:
    """4-step tiered resolver. Pure logic, no I/O. Stops at first hit.

    Step 1 — LEARNED:  learned_model is not None → AUTO(model=learned_model).
    Step 2 — EXACT:    resolve_exact finds exactly one PO model → AUTO(model).
    Step 3 — WALK:     resolve_model(Tier-2 walk) → AUTO, PROPOSE, or NEEDS_INPUT.
                       AUTO from walk → AUTO. PROPOSE → PROPOSE. NEEDS_INPUT → step 4.
    Step 4 — ASK:      no confident resolution → NEEDS_MODEL(model=None).

    Never guesses. A PROPOSE result blocks scanning until the operator re-scans
    the same barcode; a NEEDS_MODEL result blocks until the operator types a model.
    """
    # Step 1: LEARNED
    if learned_model is not None:
        return ModelScanResult(verdict=ScanVerdict.AUTO, model=learned_model)

    # Step 2: EXACT — unique normalized match against PO model list
    exact = resolve_exact(raw_barcode, po_models)
    if exact is not None:
        return ModelScanResult(verdict=ScanVerdict.AUTO, model=exact)

    # Step 3: WALK — forward-only subsequence matcher (Tier 2 of resolve_model;
    # Tier 1 is the same exact check as step 2, so it cannot AUTO here for
    # well-formed barcodes, but the branch is kept for correctness)
    walk = resolve_model(raw_barcode, po_models)
    if walk.status == MatchStatus.AUTO:
        return ModelScanResult(verdict=ScanVerdict.AUTO, model=walk.model)
    if walk.status == MatchStatus.PROPOSE:
        return ModelScanResult(verdict=ScanVerdict.PROPOSE, model=walk.model)

    # Step 4: ASK — zero or ambiguous walk candidates
    return ModelScanResult(verdict=ScanVerdict.NEEDS_MODEL, model=None)
