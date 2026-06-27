"""
Owns: adversarial known-answer tests for model_matches_barcode and resolve_model.
Must not: perform I/O; must not import adapters.
May import: pytest, core.matching.

not_measured: non-ASCII / Unicode characters in barcodes; barcodes > 200 characters;
              concurrent calls to resolve_model; locale-dependent case folding.

Mutation targets (mutmut must kill every one of these mutants):
  - Forward-only property: a mutant that resets barcode_pos on each model character
    will find '7' behind the locked position in test_critical_twin_forward_only_rejects.
  - Character equality: a mutant replacing `!=` with `<` in the inner scan loop
    fails test_exact_barcode_matches_itself (correct char skipped).
  - PROPOSE→AUTO flip: a mutant replacing MatchStatus.PROPOSE with MatchStatus.AUTO in
    Tier 2 is killed by any test that asserts status is PROPOSE.
  - Skip Tier 1: a mutant that removes the exact-equality tier falls through to PROPOSE
    where AUTO is required — killed by test_resolve_tier1_exact_base_with_variant_on_po_auto
    and test_resolve_tier1_hyphenated_variant_barcode_auto.
  - Normalize_key bypass: a mutant replacing normalize_key with identity in Tier 1 misses
    "B36-CL80-SNS-X" as exact match for "B36CL80SNSX" — killed by
    test_resolve_tier1_hyphenated_variant_barcode_auto.
  - Empty-input guard: a mutant dropping `if not model or not barcode` allows empty
    model "" to match any barcode in test_empty_model_returns_false.
"""

from __future__ import annotations

from core.matching import MatchResult, MatchStatus, model_matches_barcode, resolve_model

# ── model_matches_barcode — happy path ───────────────────────────────────────


def test_junk_prefix_matches() -> None:
    # Barcode "12z SHX78CM5N": junk prefix '1','2','z',' ' is skipped; walk finds
    # S,H,X,7,8,C,M,5,N in order after the prefix.
    assert model_matches_barcode("SHX78CM5N", "12z SHX78CM5N") is True


def test_junk_split_mid_model_matches() -> None:
    # Barcode "shx78 bpy3 cm50n": vendor junk tokens 'bpy3' are interleaved mid-model.
    # Positions: s(0)h(1)x(2)7(3)8(4) (5)b(6)p(7)y(8)3(9) (10)c(11)m(12)5(13)0(14)n(15)
    # Walk for "SHX78CM5N": S→s(0) H→h(1) X→x(2) 7→7(3) 8→8(4) C→(skip 5..10)→c(11)
    #   M→m(12) 5→5(13) N→(skip 0)→n(15) — all consumed forward, no backtrack.
    assert model_matches_barcode("SHX78CM5N", "shx78 bpy3 cm50n") is True


def test_exact_barcode_matches_itself() -> None:
    assert model_matches_barcode("SHX78CM5N", "SHX78CM5N") is True


def test_case_insensitive_match() -> None:
    assert model_matches_barcode("shx78cm5n", "SHX78CM5N") is True
    assert model_matches_barcode("SHX78CM5N", "shx78cm5n") is True


def test_model_as_prefix_of_barcode_matches() -> None:
    # Model is shorter; trailing barcode characters are irrelevant.
    assert model_matches_barcode("ABC", "ABCXYZ") is True


# ── model_matches_barcode — THE CRITICAL TWIN TEST ───────────────────────────


def test_critical_twin_forward_only_rejects_wrong_twin() -> None:
    """THE CORE SAFETY PROOF — forward-only walk must reject the near-twin model.

    Barcode:  "shx78 bpy3 cm50n"
    Positions: s(0) h(1) x(2) 7(3) 8(4) ' '(5) b(6) p(7) y(8) 3(9) ' '(10)
               c(11) m(12) 5(13) 0(14) n(15)

    Walk for model "SHP78CM5N" (wrong twin, X→P mismatch):
      's' → found at pos 0; advance to pos 1
      'h' → found at pos 1; advance to pos 2
      'p' → scan from pos 2: x(no) 7(no) 8(no) ' '(no) b(no) p(YES) at pos 7; advance to pos 8
      '7' → scan from pos 8: y(no) 3(no) ' '(no) c(no) m(no) 5(no) 0(no) n(no) → EXHAUSTED

    The '7' was at position 3, which is now behind the locked position (pos 8).
    Forward-only prevents backtracking: those positions are gone → return False.

    A mutant that resets barcode_pos for each model character (allowing backtracking)
    would find '7' at position 3 and continue — that mutant must be killed by this test.
    A mutant that replaces `!= model_char` with `< model_char` in the scan loop would
    skip over the correct character — that mutant is also killed by this test.
    """
    assert model_matches_barcode("SHP78CM5N", "shx78 bpy3 cm50n") is False


# ── model_matches_barcode — twin self-match / cross-match ────────────────────


def test_twin_matches_itself_not_sibling_clean_barcode() -> None:
    # With a clean barcode (no junk), each twin matches only itself, not the other.
    assert model_matches_barcode("SHX78CM5N", "SHX78CM5N") is True
    assert model_matches_barcode("SHP78CM5N", "SHP78CM5N") is True
    assert model_matches_barcode("SHX78CM5N", "SHP78CM5N") is False
    assert model_matches_barcode("SHP78CM5N", "SHX78CM5N") is False


# ── model_matches_barcode — fail-closed edge cases ───────────────────────────


def test_empty_model_returns_false() -> None:
    # Fail-closed: an empty model string must never accidentally match anything.
    assert model_matches_barcode("", "SHX78CM5N") is False


def test_empty_barcode_returns_false() -> None:
    # Fail-closed: a non-empty model cannot be found in an empty barcode.
    assert model_matches_barcode("SHX78CM5N", "") is False


def test_both_empty_returns_false() -> None:
    assert model_matches_barcode("", "") is False


def test_model_longer_than_barcode_returns_false() -> None:
    # Cannot fit more model characters than there are barcode characters.
    assert model_matches_barcode("ABCDEFGH", "AB") is False


def test_model_equal_length_wrong_order_returns_false() -> None:
    # Barcode "ACB": A(0) C(1) B(2). Model "ABC":
    #   A→A(0); B→C(no)→B(YES)(2); C→exhausted(3) → False.
    assert model_matches_barcode("ABC", "ACB") is False


def test_model_equal_length_exact_returns_true() -> None:
    assert model_matches_barcode("ABC", "ABC") is True


# ── resolve_model ─────────────────────────────────────────────────────────────


def test_resolve_exactly_one_match_is_auto() -> None:
    # Clean barcode "SHX78CM5N": SHX model matches (exact), SHP does not (X≠P, no P in barcode).
    result = resolve_model("SHX78CM5N", ["SHX78CM5N", "SHP78CM5N"])
    assert result.status is MatchStatus.AUTO
    assert result.model == "SHX78CM5N"
    assert result.candidates == []


def test_resolve_zero_matches_is_needs_input_empty_candidates() -> None:
    # Barcode "ZZZZZZZ" shares no subsequence structure with either PO model.
    result = resolve_model("ZZZZZZZ", ["SHX78CM5N", "SHP78CM5N"])
    assert result.status is MatchStatus.NEEDS_INPUT
    assert result.model is None
    assert result.candidates == []


def test_resolve_ambiguous_two_or_more_is_needs_input_with_candidates() -> None:
    """A pathological barcode that completes BOTH twin walks → NEEDS_INPUT with both candidates.

    Barcode "SHXP78CM5N": S(0) H(1) X(2) P(3) 7(4) 8(5) C(6) M(7) 5(8) N(9)

    Walk for SHX78CM5N: S(0) H(1) X(2) 7(4) 8(5) C(6) M(7) 5(8) N(9) → True
      (P at pos 3 is skipped while scanning for '7')
    Walk for SHP78CM5N: S(0) H(1) P(3) 7(4) 8(5) C(6) M(7) 5(8) N(9) → True
      (X at pos 2 is skipped while scanning for 'P')

    Both models consume their characters in order → ambiguous.
    resolve_model must NOT auto-pick; it must return NEEDS_INPUT with both candidates.

    A mutant replacing `len(walked) == 1` with `len(walked) >= 1` in Tier 2 would
    propose SHX78CM5N (first walk match) — this test kills that mutant.
    """
    result = resolve_model("SHXP78CM5N", ["SHX78CM5N", "SHP78CM5N"])
    assert result.status is MatchStatus.NEEDS_INPUT
    assert result.model is None
    assert sorted(result.candidates) == ["SHP78CM5N", "SHX78CM5N"]


def test_resolve_empty_po_models_is_needs_input() -> None:
    result = resolve_model("SHX78CM5N", [])
    assert result.status is MatchStatus.NEEDS_INPUT
    assert result.model is None
    assert result.candidates == []


def test_resolve_always_returns_match_result_never_none() -> None:
    # resolve_model must never return None — always a typed MatchResult.
    result = resolve_model("anything", [])
    assert isinstance(result, MatchResult)


def test_resolve_single_model_on_po_that_matches_is_auto() -> None:
    # Single model on PO and barcode matches it → AUTO.
    result = resolve_model("SHX78CM5N", ["SHX78CM5N"])
    assert result.status is MatchStatus.AUTO
    assert result.model == "SHX78CM5N"


def test_resolve_single_model_on_po_that_does_not_match_is_needs_input() -> None:
    result = resolve_model("ZZZZZZZ", ["SHX78CM5N"])
    assert result.status is MatchStatus.NEEDS_INPUT
    assert result.model is None
    assert result.candidates == []


# ── resolve_model — two-tier proof set ───────────────────────────────────────
#
# Each row asserts a full MatchResult. The PROPOSE/AUTO split is the primary
# mutation target: any mutant that flips a walk-only PROPOSE to AUTO, or drops
# the exact tier, must fail at least one row.


def test_resolve_tier1_messy_barcode_falls_to_walk_propose() -> None:
    """Junk prefix prevents Tier-1 exact match → Tier-2 walk → PROPOSE the correct twin.

    Barcode "12z SHX78CM5N": normalize_key → "12zshx78cm5n" ≠ "shx78cm5n" → 0 exact.
    Walk finds SHX78CM5N (test_junk_prefix_matches) but not SHP78CM5N → PROPOSE SHX78CM5N.

    Mutmut kill: a mutant returning AUTO for Tier-2 single-walk-match fails this assertion.
    """
    result = resolve_model("12z SHX78CM5N", ["SHX78CM5N", "SHP78CM5N"])
    assert result.status is MatchStatus.PROPOSE
    assert result.model == "SHX78CM5N"
    assert result.candidates == []


def test_resolve_tier1_twin_not_on_po_zero_candidates() -> None:
    # "SHP78CM5N" → no exact (shp≠shx), no walk (P locked behind X position) → NEEDS_INPUT [].
    result = resolve_model("SHP78CM5N", ["SHX78CM5N"])
    assert result.status is MatchStatus.NEEDS_INPUT
    assert result.model is None
    assert result.candidates == []


def test_resolve_tier1_exact_base_with_variant_on_po_no_overprompt_auto() -> None:
    """Clean base-model barcode exactly equals one PO model → AUTO with no over-prompt.

    Tier 1: normalize_key("DEC3050R") = "dec3050r" matches "DEC3050R" but not "DEC3050R/L"
    (slash is not stripped) → 1 exact → AUTO. The variant co-on-PO must not trigger a prompt.

    Mutmut kill: a mutant skipping Tier 1 falls to Tier 2 where only one model walks
    (DEC3050R/L cannot fit into "DEC3050R") → PROPOSE, not AUTO — this test fails.
    """
    result = resolve_model("DEC3050R", ["DEC3050R", "DEC3050R/L"])
    assert result.status is MatchStatus.AUTO
    assert result.model == "DEC3050R"
    assert result.candidates == []


def test_resolve_tier2_variant_barcode_single_model_po_propose() -> None:
    """Variant barcode not an exact match for the single PO model → walk proposes.

    normalize_key("DEC3050R/L") = "dec3050r/l" ≠ "dec3050r" → 0 exact.
    Walk: "DEC3050R" is a subsequence of "DEC3050R/L" → PROPOSE DEC3050R.
    Operator sees the model name and catches that the unit is actually a variant.

    Mutmut kill: a mutant returning AUTO here fails this assertion.
    """
    result = resolve_model("DEC3050R/L", ["DEC3050R"])
    assert result.status is MatchStatus.PROPOSE
    assert result.model == "DEC3050R"
    assert result.candidates == []


def test_resolve_tier2_mid_insertion_is_propose() -> None:
    """Mid-insertion barcode (feature code inserted mid-string) must not auto-bind base.

    Barcode "BI-36UID/O-LH", PO model "BI-36U/O-LH" (base, missing 'ID' suffix).
    normalize_key: "bi36uid/olh" ≠ "bi36u/olh" → 0 exact.
    Walk: BI-36U/O-LH is a subsequence of BI-36UID/O-LH (walk skips I,D after U) → PROPOSE.
    A silent AUTO here would receive the wrong SKU — PROPOSE lets the operator catch it.
    """
    result = resolve_model("BI-36UID/O-LH", ["BI-36U/O-LH"])
    assert result.status is MatchStatus.PROPOSE
    assert result.model == "BI-36U/O-LH"
    assert result.candidates == []


def test_resolve_tier1_exact_mid_insertion_with_base_on_po_auto() -> None:
    """Exact variant barcode with both base and variant on PO → Tier-1 picks the exact one.

    Tier 1: normalize_key("BI-36UID/O-LH") = "bi36uid/olh" matches only "BI-36UID/O-LH"
    (not "BI-36U/O-LH" = "bi36u/olh") → 1 exact → AUTO the correct variant.

    Mutmut kill: skipping Tier 1 falls to Tier 2 where both walk-match → NEEDS_INPUT.
    """
    result = resolve_model("BI-36UID/O-LH", ["BI-36U/O-LH", "BI-36UID/O-LH"])
    assert result.status is MatchStatus.AUTO
    assert result.model == "BI-36UID/O-LH"
    assert result.candidates == []


def test_resolve_tier1_exact_slash_model_with_base_on_po_auto() -> None:
    # CL3050UG/S/P/R exactly matches itself; base CL3050U/S/P/R has different key → AUTO.
    result = resolve_model("CL3050UG/S/P/R", ["CL3050U/S/P/R", "CL3050UG/S/P/R"])
    assert result.status is MatchStatus.AUTO
    assert result.model == "CL3050UG/S/P/R"
    assert result.candidates == []


def test_resolve_tier2_junk_barcode_two_walk_matches_needs_input() -> None:
    """Junk-bearing barcode (per-unit serial suffix) fails Tier-1 and walks two models.

    Barcode "WRF560SEHZ00XP" has extra suffix — normalize_key ≠ either PO model key.
    Walk: "WRF560" is a subsequence of "WRF560SEHZ00XP" → True.
          "WRF560SEHZ00" is a subsequence of "WRF560SEHZ00XP" → True.
    Two walk matches → NEEDS_INPUT both.
    """
    result = resolve_model("WRF560SEHZ00XP", ["WRF560", "WRF560SEHZ00"])
    assert result.status is MatchStatus.NEEDS_INPUT
    assert result.model is None
    assert sorted(result.candidates) == ["WRF560", "WRF560SEHZ00"]


def test_resolve_tier1_hyphenated_variant_barcode_auto() -> None:
    """Hyphenated variant barcode exactly matches its hyphenated PO model via normalize_key.

    Barcode "B36CL80SNSX": normalize_key → "b36cl80snsx".
    "B36CL80SNS"  → "b36cl80sns"  ≠ "b36cl80snsx"
    "B36-CL80-SNS-X" → "b36cl80snsx" = "b36cl80snsx" → 1 exact → AUTO the correct variant.

    Under the old prefix-collision guard this returned NEEDS_INPUT (over-prompt).
    Under the two-tier resolver it correctly identifies the scanned variant → AUTO.

    Mutmut kill: removing normalize_key in Tier 1 (raw string compare) misses the
    hyphenated model — falls to walk → PROPOSE, not AUTO, failing this assertion.
    """
    result = resolve_model("B36CL80SNSX", ["B36CL80SNS", "B36-CL80-SNS-X"])
    assert result.status is MatchStatus.AUTO
    assert result.model == "B36-CL80-SNS-X"
    assert result.candidates == []
