"""
Owns: tests for core.model_resolution.resolve_scan — tiered precedence,
      PROPOSE/NEEDS_MODEL outcomes, and the save-and-learn contract.
Must not: import adapters or services; no I/O.
May import: pytest, core.model_resolution, core.matching.

not_measured: multi-PO scenarios, cross-PO resolution (separate ticket).

PASS  thresholds (pre-declared):
  PASS:    all assertions green.
  PARTIAL: none — all core logic must be covered.
  KILL:    any assertion failure.
"""

from __future__ import annotations

from core.model_resolution import ScanVerdict, resolve_scan

# ── helpers ───────────────────────────────────────────────────────────────────

_MODELS = ["B36-CL80", "SHX78CM5N", "WMB568GWW"]
_NO_MATCH_MODELS = ["ALPHA-1", "BETA-2", "GAMMA-3"]


# ── Step 1: LEARNED beats everything ─────────────────────────────────────────


def test_learned_returns_auto_with_learned_model() -> None:
    """learned_model not None → AUTO with that model, regardless of po_models.

    Mutation kill: removing the step-1 guard → falls to exact/walk → different result.
    """
    result = resolve_scan("ANY-BARCODE", _MODELS, learned_model="WMB568GWW")
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "WMB568GWW"


def test_learned_beats_exact_match() -> None:
    """LEARNED takes priority even when the barcode exactly matches a PO model.

    Precondition: "B36CL80" normalizes to "b36cl80" == normalize("B36-CL80").
    Without step 1 guard, resolve_exact would fire first and return 'B36-CL80'.
    With step 1 guard, learned_model is returned without consulting po_models.

    Mutation kill: swapping step order returns AUTO on a different model.
    """
    result = resolve_scan("B36CL80", ["B36-CL80", "OTHER"], learned_model="LEARNED-MDL")
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "LEARNED-MDL"
    assert result.model != "B36-CL80"


def test_learned_beats_walk_propose() -> None:
    """LEARNED takes priority when a walk would propose (save-and-learn contract).

    After a NEEDS_MODEL typed answer is saved via save_barcode_mapping, the
    next scan for the same raw barcode provides learned_model from the DB.
    That scan resolves as AUTO instantly — no PROPOSE prompt, no typing.

    Mutation kill: removing step-1 guard causes a PROPOSE, not AUTO.
    """
    # "SHX78" is a subsequence of "SHX78CM5N" — walk would PROPOSE "SHX78CM5N"
    result = resolve_scan("SHX78", ["SHX78CM5N"], learned_model="SHX78CM5N")
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "SHX78CM5N"


# ── Step 2: EXACT ─────────────────────────────────────────────────────────────


def test_exact_returns_auto_when_no_learned() -> None:
    """Barcode exactly normalizes to one PO model → AUTO.

    Mutation kill: removing step-2 guard falls through to walk → PROPOSE or NEEDS_MODEL.
    """
    # normalize("B36-CL80") == normalize("B36CL80") == "b36cl80"
    result = resolve_scan("B36CL80", ["B36-CL80", "SHX78CM5N"], learned_model=None)
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "B36-CL80"


def test_exact_two_matches_falls_through_to_needs_model() -> None:
    """Two distinct models with the same normalized key → resolve_exact returns None.

    Step 2 returns None; step 3 (walk) finds both via exact Tier 1 → NEEDS_INPUT;
    step 4 → NEEDS_MODEL.

    Mutation kill: treating multiple matches as a single match produces AUTO.
    """
    result = resolve_scan("MDL-A", ["MDL-A", "MDLA"], learned_model=None)
    assert result.verdict == ScanVerdict.NEEDS_MODEL
    assert result.model is None


def test_exact_no_match_falls_through_to_walk() -> None:
    """No exact match → falls through to step 3 (walk) for resolution."""
    # "SHX78CM5N" is a subsequence of barcode "SHX78CM5N-001" — walk should PROPOSE
    result = resolve_scan("SHX78CM5N-001", ["SHX78CM5N", "WMB568GWW"], learned_model=None)
    assert result.verdict == ScanVerdict.PROPOSE
    assert result.model == "SHX78CM5N"


# ── Step 3: WALK ──────────────────────────────────────────────────────────────


def test_walk_propose_returns_propose() -> None:
    """One walk candidate → PROPOSE with that model.

    Mutation kill: changing PROPOSE → AUTO would skip the operator confirm step,
    violating the safety invariant (never auto-receive an ambiguous scan).
    """
    # "WMB568GWW" is a subsequence of barcode "WMB568GWW-SCAN"; "SHX78CM5N" is not
    result = resolve_scan("WMB568GWW-SCAN", ["WMB568GWW", "SHX78CM5N"], learned_model=None)
    assert result.verdict == ScanVerdict.PROPOSE
    assert result.model == "WMB568GWW"


def test_walk_zero_candidates_returns_needs_model() -> None:
    """No walk candidates → NEEDS_MODEL.

    Mutation kill: returning PROPOSE on zero candidates would show a null model.
    """
    result = resolve_scan("ZZZZZ", ["B36-CL80", "SHX78CM5N"], learned_model=None)
    assert result.verdict == ScanVerdict.NEEDS_MODEL
    assert result.model is None


def test_walk_ambiguous_two_candidates_returns_needs_model() -> None:
    """Two walk candidates → NEEDS_INPUT from resolve_model → NEEDS_MODEL.

    Mutation kill: returning PROPOSE on ambiguous walk silently picks one.
    """
    # "A" is a subsequence of both "ALPHA" and "AXXX"
    result = resolve_scan("A", ["ALPHA", "AXXX"], learned_model=None)
    assert result.verdict == ScanVerdict.NEEDS_MODEL
    assert result.model is None


def test_walk_auto_degenerate_empty_normalization() -> None:
    """Degenerate: barcode normalizes to '' and one PO model also normalizes to ''.

    resolve_exact fails (exact_model_match returns False on empty); resolve_model
    Tier 1 finds the empty match and returns AUTO. This exercises the
    walk.status == MatchStatus.AUTO branch in resolve_scan.

    Mutation kill: removing that branch returns NEEDS_MODEL for this edge case.
    """
    # normalize_key("-") == "" == normalize_key("")
    result = resolve_scan("", ["-"], learned_model=None)
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "-"


# ── Step 4: ASK ───────────────────────────────────────────────────────────────


def test_empty_po_models_returns_needs_model() -> None:
    """No PO models at all → NEEDS_MODEL (no PO loaded or all claimed)."""
    result = resolve_scan("ANYTHING", [], learned_model=None)
    assert result.verdict == ScanVerdict.NEEDS_MODEL
    assert result.model is None


# ── Structural ────────────────────────────────────────────────────────────────


def test_result_is_frozen_dataclass() -> None:
    """ModelScanResult is immutable — callers cannot mutate a returned result."""
    result = resolve_scan("X", ["X"], learned_model=None)
    assert result.verdict == ScanVerdict.AUTO
    try:
        result.verdict = ScanVerdict.NEEDS_MODEL  # type: ignore[misc]
        raise AssertionError("should have raised FrozenInstanceError")
    except AssertionError:
        raise
    except Exception:
        pass


def test_no_fuzzy_logic_in_resolve_scan() -> None:
    """Behavioral: resolve_scan never produces PROPOSE from a partial prefix alone.

    "SHX" is NOT a subsequence of "SHX78CM5N" (it is — this verifies the walk
    does find it), but there must be no score or threshold involved.
    Verified here by ensuring two models with partial matches produce NEEDS_MODEL
    (ambiguous walk) rather than any score-ranked pick.

    Mutation kill: introducing a threshold pick would break the ambiguous case.
    """
    result = resolve_scan("A", ["ALPHA", "AB"], learned_model=None)
    assert result.verdict == ScanVerdict.NEEDS_MODEL
