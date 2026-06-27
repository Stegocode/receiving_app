"""
Owns: known-answer tests for core.matching exact normalized match functions.
Must not: perform I/O; must not import adapters.
May import: pytest, core.matching.

not_measured: real barcode scanner device, non-ASCII model strings,
              real network or DB calls.
"""

from core.matching import exact_model_match, resolve_exact

# ── exact_model_match — positive cases ────────────────────────────────────────


def test_exact_match_identical_returns_true():
    assert exact_model_match("SHX78CM5N", "SHX78CM5N") is True


def test_exact_match_case_insensitive():
    assert exact_model_match("shx78cm5n", "SHX78CM5N") is True
    assert exact_model_match("SHX78CM5N", "shx78cm5n") is True


def test_exact_match_strips_spaces():
    assert exact_model_match("SHX 78CM 5N", "SHX78CM5N") is True
    assert exact_model_match("SHX78CM5N", "SHX 78CM 5N") is True


def test_exact_match_strips_hyphens():
    assert exact_model_match("SHX-78CM-5N", "SHX78CM5N") is True
    assert exact_model_match("SHX78CM5N", "SHX-78CM-5N") is True


def test_exact_match_strips_spaces_and_hyphens_combined():
    assert exact_model_match("SHX 78-CM 5N", "SHX78CM5N") is True


# ── exact_model_match — fail-closed on empty ──────────────────────────────────


def test_exact_match_empty_first_returns_false():
    assert exact_model_match("", "SHX78CM5N") is False


def test_exact_match_empty_second_returns_false():
    assert exact_model_match("SHX78CM5N", "") is False


def test_exact_match_both_empty_returns_false():
    assert exact_model_match("", "") is False


def test_exact_match_space_only_returns_false():
    """A string of only spaces normalizes to empty — fail-closed."""
    assert exact_model_match("   ", "SHX78CM5N") is False


def test_exact_match_hyphen_only_returns_false():
    """A string of only hyphens normalizes to empty — fail-closed."""
    assert exact_model_match("---", "SHX78CM5N") is False


# ── Adversarial twin pairs: must NOT match ─────────────────────────────────────


def test_near_twin_shx_vs_shp_does_not_match():
    """SHX78CM5N vs SHP78CM5N — single-char X→P, must not match."""
    assert exact_model_match("SHX78CM5N", "SHP78CM5N") is False


def test_near_twin_b36cl_sns_vs_ct_sns_does_not_match():
    """B36CL80SNS vs B36CT80SNS — CL vs CT, must not match."""
    assert exact_model_match("B36CL80SNS", "B36CT80SNS") is False


def test_near_twin_b36cl_ens_vs_sns_does_not_match():
    """B36CL80ENS vs B36CL80SNS — E vs S at position 7, must not match."""
    assert exact_model_match("B36CL80ENS", "B36CL80SNS") is False


def test_near_twin_shp_cm_vs_dm_does_not_match():
    """SHP78CM5N vs SHP78DM5N — C vs D, must not match."""
    assert exact_model_match("SHP78CM5N", "SHP78DM5N") is False


def test_substring_not_a_match():
    """SHP78CM5N must NOT match a longer string that merely contains it."""
    assert exact_model_match("SHP78CM5N", "XSHP78CM5NZ") is False
    assert exact_model_match("XSHP78CM5NZ", "SHP78CM5N") is False


# ── resolve_exact — positive cases ────────────────────────────────────────────


def test_resolve_exact_single_match_returns_candidate():
    result = resolve_exact("SHX78CM5N", ["SHX78CM5N", "SHP78CM5N"])
    assert result == "SHX78CM5N"


def test_resolve_exact_hyphen_variant_matches():
    """A hyphenated barcode must resolve to the unhyphenated catalog entry."""
    result = resolve_exact("SHX-78CM-5N", ["SHX78CM5N", "SHP78CM5N"])
    assert result == "SHX78CM5N"


def test_resolve_exact_space_and_case_variant_matches():
    """Space and case variants must resolve correctly."""
    result = resolve_exact("shx 78cm 5n", ["SHX78CM5N", "SHP78CM5N"])
    assert result == "SHX78CM5N"


def test_resolve_exact_twin_pair_each_resolves_to_own():
    """Each twin resolves to itself and not the other."""
    candidates = ["SHX78CM5N", "SHP78CM5N"]
    assert resolve_exact("SHX78CM5N", candidates) == "SHX78CM5N"
    assert resolve_exact("SHP78CM5N", candidates) == "SHP78CM5N"


# ── resolve_exact — fail-closed cases ─────────────────────────────────────────


def test_resolve_exact_no_match_returns_none():
    result = resolve_exact("ZZZ999", ["SHX78CM5N", "SHP78CM5N"])
    assert result is None


def test_resolve_exact_two_matches_returns_none():
    """When two candidates normalize identically, return None (fail-closed, not a guess)."""
    result = resolve_exact("MODEL-A", ["MODEL-A", "MODEL A"])
    assert result is None


def test_resolve_exact_empty_candidates_returns_none():
    assert resolve_exact("SHX78CM5N", []) is None


def test_resolve_exact_empty_barcode_returns_none():
    assert resolve_exact("", ["SHX78CM5N"]) is None


def test_resolve_exact_near_twin_shx_does_not_claim_shp_slot():
    """Scanning SHX barcode against a PO that has only SHP must return None."""
    assert resolve_exact("SHX78CM5N", ["SHP78CM5N"]) is None
