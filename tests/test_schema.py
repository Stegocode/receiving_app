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
    # All 12 fields missing — must report at least one problem per field
    problems = validate_record({})
    assert len(problems) > 0


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
    with pytest.raises(ValidationError):
        from_dict({})


def test_validate_invalid_timestamp():
    problems = validate_record({**_VALID, "timestamp": "not-a-date"})
    assert any("timestamp" in p for p in problems)
