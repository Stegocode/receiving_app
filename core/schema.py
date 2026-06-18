"""
Owns: ReceivingRecord dataclass and SCHEMA_VERSION constant.
Must not: perform any I/O; must not import adapters or services.
May import: stdlib, core.errors.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1


@dataclass
class ReceivingRecord:
    """Output record — the contract with everything downstream.

    Idempotency key: receiving_id. Any adapter that receives the same
    receiving_id twice must treat the second call as a no-op.

    T-05 adds: validate_record(), from_dict(), to_dict(), migrate().
    """

    truck: str
    stop: str
    sales_order: str
    model_number: str
    product_category: str
    product_size: dict  # {w, d, h} in inches
    quantity: int
    receiving_id: str  # stable idempotency key
    timestamp: str  # ISO-8601
    match_status: str  # "received" | "no_match" | "needs_attention"
    purchase_order: str
    inventory_id: str
