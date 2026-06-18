"""
Owns: known-answer tests for core.schema ReceivingRecord and validator.
Must not: perform I/O; must not import adapters.
May import: pytest, core.schema, core.errors.

not_measured: real DB persistence, network calls, migration chains beyond v1.
"""

from core.schema import SCHEMA_VERSION


def test_schema_version_is_positive_integer():
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1
