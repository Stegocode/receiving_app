"""
Owns: regression tests for conformance gate_a banned-name matching.
Must not: perform I/O against git; must not import adapters.
May import: pytest, conformance.banned_name_hit.

not_measured: full gate_a integration against a real git tree.
"""

from conformance import banned_name_hit

# ── exact-case hits ───────────────────────────────────────────────────────────


def test_client_name_in_content_exact():
    assert banned_name_hit("Bas" + "co", "client is Bas" + "co appliances", "some/file.py")


def test_source_vendor_name_in_path_exact():
    assert banned_name_hit("Home" + "Source", "", "adapters/home" + "source.py")


# ── case-insensitive hits (the regression) ───────────────────────────────────


def test_sink_vendor_name_lowercase_in_path():
    """Lowercase vendor filename must be caught case-insensitively."""
    assert banned_name_hit("Mon" + "day", "", "adapters/" + "mon" + "day.py")


def test_source_vendor_name_lowercase_in_content():
    """Lowercase vendor word in file body must be caught case-insensitively."""
    assert banned_name_hit(
        "Home" + "Source", "scrapes home" + "source portal", "adapters/source.py"
    )


def test_sink_vendor_name_uppercase_in_path():
    assert banned_name_hit("Mon" + "day", "", "adapters/MON" + "DAY.py")


def test_client_name_mixed_case_in_content():
    assert banned_name_hit("Bas" + "co", "BAS" + "CO Appliances", "config.py")


# ── true-negatives (clean content must not be flagged) ───────────────────────


def test_clean_file_not_flagged():
    assert not banned_name_hit("Mon" + "day", "result sink adapter", "adapters/sink.py")


def test_clean_path_not_flagged():
    assert not banned_name_hit("Home" + "Source", "purchase order source", "adapters/source.py")
