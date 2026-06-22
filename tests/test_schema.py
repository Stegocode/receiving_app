"""
Owns: known-answer tests for core.schema ReceivingRecord and validator.
Must not: perform I/O; must not import adapters.
May import: pytest, core.schema, core.errors.

not_measured: real DB persistence, network calls, migration chains beyond v1.
"""

import pytest

from core.errors import ValidationError
from core.schema import SCHEMA_VERSION, from_dict, to_dict, validate_record

_VALID = {
    "truck": "T1",
    "stop": "S1",
    "sales_order": "SO-001",
    "model_number": "MDL-001",
    "product_category": "Furniture",
    "product_size": {"w": 30.0, "d": 20.0, "h": 10.0},
    "quantity": 2,
    "receiving_id": "abc-123",
    "timestamp": "2026-06-19T10:00:00",
    "match_status": "received",
    "purchase_order": "PO-001",
    "inventory_id": "INV-001",
}


def test_schema_version_is_positive_integer():
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1


def test_validate_empty_dict_returns_problems():
    # All 12 fields missing — must report at least one problem per field.
    # Exact membership checks kill mutations that replace problem strings with
    # None (mutmut_5, 38, 53) or garbled text (mutmut_39, 40, 54, 55).
    problems = validate_record({})
    assert len(problems) > 0
    assert "truck: missing required field" in problems
    assert "quantity: missing required field" in problems
    assert "product_size: missing required field" in problems


def test_validate_valid_record_returns_empty():
    assert validate_record(_VALID) == []


def test_validate_invalid_match_status():
    # "wrong" is not in {"received", "no_match", "needs_attention"}
    problems = validate_record({**_VALID, "match_status": "wrong"})
    assert any("match_status" in p for p in problems)


def test_round_trip():
    record = from_dict(_VALID)
    assert from_dict(to_dict(record)) == record


def test_validate_product_size_negative_dimension():
    # w = -1 violates the >= 0 constraint
    problems = validate_record({**_VALID, "product_size": {"w": -1.0, "d": 20.0, "h": 10.0}})
    assert any("product_size" in p for p in problems)


def test_validate_quantity_zero():
    # quantity must be a positive integer (> 0)
    problems = validate_record({**_VALID, "quantity": 0})
    assert any("quantity" in p for p in problems)


def test_from_dict_raises_validation_error_on_bad_data():
    # match= kills mutmut_5 (ValidationError(None)) and case-mutation survivors.
    with pytest.raises(ValidationError, match="Record failed validation"):
        from_dict({})


def test_validate_invalid_timestamp():
    problems = validate_record({**_VALID, "timestamp": "not-a-date"})
    assert any("timestamp" in p for p in problems)


def test_validate_string_field_wrong_type():
    # L61: str field contains a non-str value — must report type error with actual type.
    # `and "int" in p` kills mutmut_8: replaces `type(data[field]).__name__`
    # with `type(None).__name__` ("NoneType" doesn't contain "int").
    problems = validate_record({**_VALID, "purchase_order": 999})
    assert any("purchase_order" in p and "str" in p for p in problems)
    assert any("int" in p for p in problems)


def test_validate_receiving_id_empty():
    # L63: receiving_id is whitespace-only — must report non-empty violation.
    # Exact membership check kills mutmut_15: "XXreceiving_id: must be non-emptyXX"
    # is not equal to the correct string, so `in problems` (list membership) fails.
    problems = validate_record({**_VALID, "receiving_id": "  "})
    assert "receiving_id: must be non-empty" in problems


def test_validate_quantity_wrong_type():
    # L81: quantity is a float, not an int — must report type error with "float".
    # `and "float" in p` kills mutmut_44: replaces type name with "NoneType".
    problems = validate_record({**_VALID, "quantity": 2.5})
    assert any("quantity" in p for p in problems)
    assert any("float" in p for p in problems)


def test_validate_quantity_bool_rejected():
    # L81: bool is a subclass of int — must be treated as wrong type, not int.
    # `and "bool" in p` kills mutmut_44 via the bool path.
    problems = validate_record({**_VALID, "quantity": True})
    assert any("quantity" in p for p in problems)
    assert any("bool" in p for p in problems)


def test_validate_product_size_not_dict():
    # L89: product_size is a string, not a dict — must report type error with "str".
    # `and "str" in p` kills mutmut_58: replaces type name with "NoneType".
    problems = validate_record({**_VALID, "product_size": "big"})
    assert any("product_size" in p and "str" in p for p in problems)


def test_validate_product_size_missing_key():
    # L93: product_size dict is missing a required dimension key
    problems = validate_record({**_VALID, "product_size": {"w": 1.0, "d": 2.0}})
    assert any("product_size" in p and "missing key" in p for p in problems)


def test_validate_product_size_wrong_value_type():
    # L95: product_size dimension value is a string, not numeric.
    # `and "str" in p` kills mutmut_70: replaces type name with "NoneType".
    problems = validate_record({**_VALID, "product_size": {"w": "wide", "d": 2.0, "h": 3.0}})
    assert any("product_size" in p and "numeric" in p for p in problems)
    assert any("str" in p for p in problems)


def test_from_dict_error_message_format():
    """ValidationError message starts with the expected header and uses plain newline separation.

    Kills mutmut_7: prefix "XXRecord failed validation:\\nXX" — message would not start
    with "Record failed validation".
    Kills mutmut_11: "XX\\nXX".join(problems) — message would contain literal "XX".
    """
    with pytest.raises(ValidationError) as exc_info:
        from_dict({**_VALID, "truck": 123, "stop": None})
    msg = str(exc_info.value)
    assert msg.startswith("Record failed validation:\n")
    assert "\n  " in msg  # problems are indented with two spaces after newline
    assert "XX" not in msg  # guards against garbled join separator
