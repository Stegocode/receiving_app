"""
Owns: known-answer tests for core.matching pure functions.
Must not: perform I/O; must not import adapters.
May import: pytest, core.matching.

not_measured: real barcode scanner device, EAN-14 edge cases beyond listed fixtures,
              non-ASCII barcodes, real network or DB calls.
"""

from core.matching import find_best_match, match_score, normalize, strip_ean14


def test_exact_match_score_is_1():
    # normalize("widget-a") == normalize("widget-a") → SequenceMatcher → 1.0
    assert match_score("widget-a", "widget-a") == 1.0


def test_ean14_leading_zero_stripped_matches():
    # "01234567890123": 14 digits, starts with '0' → strip → "1234567890123"
    # candidate "1234567890123" → match_score = 1.0 → above threshold
    result, score = find_best_match("01234567890123", ["1234567890123"])
    assert result == "1234567890123"
    assert score == 1.0


def test_strong_match_beats_decoys():
    # normalize("widget-a") vs normalize("widget-a") → 1.0
    # vs normalize("gadget-z") and normalize("other-x") → both < 1.0
    result, score = find_best_match("widget-a", ["gadget-z", "widget-a", "other-x"])
    assert result == "widget-a"
    assert score == 1.0


def test_below_threshold_returns_none():
    # SequenceMatcher(None, "abc", "xyz").ratio() == 0.0 (no common chars)
    # 0.0 < default threshold 0.6 → (None, 0.0)
    result, score = find_best_match("abc", ["xyz"])
    assert result is None
    assert score == 0.0


def test_empty_barcode_returns_none():
    # strip_ean14("") = ""; normalize("") = "" → guard fires → (None, 0.0)
    result, score = find_best_match("", ["widget-a"])
    assert result is None
    assert score == 0.0


def test_empty_candidates_returns_none():
    # no candidates → (None, 0.0) immediately
    result, score = find_best_match("widget-a", [])
    assert result is None
    assert score == 0.0


def test_whitespace_only_barcode_returns_none():
    # strip_ean14("   ") = "   "; normalize("   ") = "" → guard fires → (None, 0.0)
    result, score = find_best_match("   ", ["widget-a"])
    assert result is None
    assert score == 0.0


def test_tied_scores_first_candidate_wins():
    # normalize("aa") = "aa"; normalize("ab") = "ab"; normalize("ba") = "ba"
    # SequenceMatcher("aa","ab").ratio() = 2*1/(2+2) = 0.5  (one 'a' matched)
    # SequenceMatcher("aa","ba").ratio() = 2*1/(2+2) = 0.5  (one 'a' matched)
    # threshold=0.4 so both qualify; strict > means first candidate keeps the win
    result, score = find_best_match("aa", ["ab", "ba"], threshold=0.4)
    assert result == "ab"
    assert score == 0.5


def test_strip_ean14_non_digit_14_char_not_stripped():
    """14-char string that starts with '0' but contains non-digits is NOT stripped.

    Kills mutmut_1 (`and → or barcode.startswith("0")`) and
    mutmut_2 (`and → or barcode.isdigit()`): both weaken the guard in a way
    that would incorrectly strip non-EAN-14 barcodes.
    """
    barcode = "0ABCDE7890123"  # 13 chars, has non-digits — should not be stripped
    assert strip_ean14(barcode) == barcode

    non_digit_14 = "0ABCDE78901234"  # 14 chars, non-digits, starts with "0"
    assert strip_ean14(non_digit_14) == non_digit_14


def test_normalize_collapses_internal_whitespace():
    """Multiple internal spaces collapse to a single space in normalized output.

    Kills mutmut_3 (`" ".join` → `"XX XX".join`): the mutation changes the
    separator so "word1XX XXword2" != "word1 word2".
    """
    assert normalize("hello   world") == "hello world"
    assert normalize("  foo  bar  baz  ") == "foo bar baz"


def test_find_best_match_initial_best_match_is_none_not_empty():
    """Return value is None (not falsy-empty) when no candidate scores > initial 0.0.

    Kills mutmut_9: best_match = "" — at threshold=0.0, the function reaches
    `return best_match, best_score` with best_match never updated from its initial
    value (no score > 0.0 means the loop body never fires), so None vs "" is
    observable via `result is None`.
    """
    # normalize("xyz") vs normalize("abc") share no characters → ratio = 0.0
    # With threshold=0.0: best_score(0.0) < threshold(0.0) is False → return best_match
    result, score = find_best_match("xyz", ["abc"], threshold=0.0)
    assert result is None
    assert score == 0.0


def test_find_best_match_returns_match_when_score_equals_threshold():
    """Score exactly equal to threshold must return the match, not None.

    Kills mutmut_20: `< threshold` → `<= threshold` — the mutation rejects a
    score at the boundary (exact match with threshold=1.0 returns None instead
    of the candidate).
    """
    result, score = find_best_match("abc", ["abc"], threshold=1.0)
    assert result == "abc"
    assert score == 1.0
