"""
Owns: pure barcode/model matching functions (exact normalized match,
      forward-only sequence matcher, PO-level resolver).
Must not: perform any I/O; must not import adapters, services, or read environment variables.
May import: stdlib (dataclasses, enum).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ── Exact normalized match ─────────────────────────────────────────────────────


def normalize_key(s: str) -> str:
    """Normalize for exact-equality comparison: lowercase, remove spaces and hyphens.

    This is the canonical normalizer for deciding whether a barcode and a model
    represent the same unit. Import this function; do not duplicate the logic.
    "B36-CL80-SNS-X" and "B36CL80SNSX" collapse to the same key; "SHX78CM5N"
    and "SHP78CM5N" do not (different characters remain after stripping).
    """
    return s.lower().replace("-", "").replace(" ", "")


def exact_model_match(a: str, b: str) -> bool:
    """True iff both strings are identical under normalize_key (case-fold, strip spaces/hyphens).

    Returns False (fail-closed) when either argument is empty after normalization.
    """
    na = normalize_key(a)
    nb = normalize_key(b)
    return bool(na) and bool(nb) and na == nb


def resolve_exact(barcode: str, candidates: list[str]) -> str | None:
    """Return the single candidate that exactly matches barcode (normalized), or None.

    Returns None when zero or two-or-more candidates match. Never guesses.
    """
    matched = [c for c in candidates if exact_model_match(barcode, c)]
    return matched[0] if len(matched) == 1 else None


# ── Forward-only sequence matcher ─────────────────────────────────────────────


class MatchStatus(Enum):
    AUTO = "auto"  # exact-normalized match; safe to receive with no operator action
    PROPOSE = "propose"  # walk found one candidate; show it, receive only on ratification
    NEEDS_INPUT = "needs_input"  # zero or two-or-more candidates; operator chooses or types


@dataclass(frozen=True)
class MatchResult:
    """Typed result from resolve_model — never None.

    AUTO:        Tier-1 exact-normalized barcode matches exactly one PO model;
                 model is set, candidates is empty.
    PROPOSE:     Tier-2 forward-only walk found exactly one candidate;
                 model is set, candidates is empty. Operator must ratify before receiving.
    NEEDS_INPUT: Zero or two-or-more matches at any tier; model is None,
                 candidates holds every match found.
    """

    status: MatchStatus
    model: str | None
    candidates: list[str] = field(default_factory=list)


def model_matches_barcode(model: str, barcode: str) -> bool:
    """Forward-only subsequence walk: does model appear as an ordered subsequence of barcode?

    Normalizes both to lowercase; otherwise compares characters exactly.
    Advances through the barcode left-to-right, never backtracking. Once a barcode
    position is consumed it is gone — this is what makes near-twin models self-reject
    (see the adversarial twin test in tests/test_sequence_matcher.py).

    Returns False (fail-closed) when either argument is empty.
    """
    if not model or not barcode:
        return False

    model_lower = model.lower()
    barcode_lower = barcode.lower()

    barcode_pos = 0
    for model_char in model_lower:
        # Scan forward for the next needed character; never step back.
        while barcode_pos < len(barcode_lower) and barcode_lower[barcode_pos] != model_char:
            barcode_pos += 1
        if barcode_pos >= len(barcode_lower):
            return False
        barcode_pos += 1  # lock this position and advance past it

    return True


def resolve_model(barcode: str, po_models: list[str]) -> MatchResult:
    """Two-tier resolver: exact-normalized equality first, forward-only walk second.

    Tier 1 — exact normalized equality (normalize_key: lowercase, strip spaces/hyphens):
      Exactly 1 match  → AUTO(model=matched, candidates=[])
      2 or more matches → NEEDS_INPUT(model=None, candidates=[all exact])

    Tier 2 — forward-only walk, reached only when Tier 1 found zero exact matches:
      Exactly 1 match  → PROPOSE(model=matched, candidates=[])
      0 or 2+ matches  → NEEDS_INPUT(model=None, candidates=[all walked])

    A walk match proposes, never autos — prefix, mid-insertion, and near-twin
    collisions cannot silently bind. Only exact-normalized equality autos.

    Always returns a MatchResult — never None.
    """
    # Tier 1 — exact normalized equality
    barcode_key = normalize_key(barcode)
    exact = [m for m in po_models if normalize_key(m) == barcode_key]
    if len(exact) == 1:
        return MatchResult(status=MatchStatus.AUTO, model=exact[0], candidates=[])
    if len(exact) >= 2:
        return MatchResult(status=MatchStatus.NEEDS_INPUT, model=None, candidates=exact)

    # Tier 2 — forward-only walk (junk-tolerant; proposes, never autos)
    walked = [m for m in po_models if model_matches_barcode(m, barcode)]
    if len(walked) == 1:
        return MatchResult(status=MatchStatus.PROPOSE, model=walked[0], candidates=[])
    return MatchResult(status=MatchStatus.NEEDS_INPUT, model=None, candidates=walked)
