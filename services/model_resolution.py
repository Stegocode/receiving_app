"""
Owns: model-scan resolution service — wraps the 4-step tiered resolver with
      repository I/O for LEARNED lookup and unclaimed-PO model list.
Must not: import concrete adapters; must not read environment variables.
May import: core.matching, core.model_resolution, core.ports.
"""

from __future__ import annotations

import logging

from core.matching import exact_model_match
from core.model_resolution import ModelScanResult, resolve_scan
from core.ports import Repository

logger = logging.getLogger(__name__)


def resolve_model_barcode(
    raw_barcode: str,
    po_number: str,
    repository: Repository,
) -> ModelScanResult:
    """Run the 4-step tiered resolver for a model-barcode scan.

    LEARNED:    repository.lookup_barcode_mapping(raw_barcode) → non-None
    EXACT/WALK: repository.unclaimed_for_po(po_number) → unique model list
    Result:     ModelScanResult(verdict, model)
    """
    learned_model = repository.lookup_barcode_mapping(raw_barcode)
    candidates = repository.unclaimed_for_po(po_number)
    po_models = list(dict.fromkeys(c["model_number"] for c in candidates))
    result = resolve_scan(raw_barcode, po_models, learned_model)
    logger.info(
        "model_resolution raw_barcode=%s po=%s verdict=%s model=%s",
        raw_barcode,
        po_number,
        result.verdict.value,
        result.model,
    )
    return result


def check_model_on_po(model: str, po_number: str, repository: Repository) -> bool:
    """Return True iff model exactly matches at least one unclaimed item on po_number.

    Uses exact_model_match (normalized: lowercase, strip spaces/hyphens).
    Always returns False for off-PO models; never fuzzy.
    """
    candidates = repository.unclaimed_for_po(po_number)
    return any(exact_model_match(model, c["model_number"]) for c in candidates)
