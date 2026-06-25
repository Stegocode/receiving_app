"""
Owns: ReceivingRecord dataclass and SCHEMA_VERSION constant.
Must not: perform any I/O; must not import adapters or services.
May import: stdlib, core.errors.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from core.errors import ValidationError

SCHEMA_VERSION = 2

_VALID_MATCH_STATUSES = {"received", "no_match", "needs_attention", "already_scanned"}
_STR_FIELDS = (
    "truck",
    "stop",
    "sales_order",
    "model_number",
    "product_category",
    "receiving_id",
    "timestamp",
    "match_status",
    "purchase_order",
    "inventory_id",
)
# Optional string fields: absent or None is acceptable; non-str is an error.
_OPTIONAL_STR_FIELDS = ("serial", "brand", "vendor", "tags")


@dataclass
class ReceivingRecord:
    """Output record — the contract with everything downstream.

    Idempotency key: receiving_id. Any adapter that receives the same
    receiving_id twice must treat the second call as a no-op.
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
    match_status: str  # "received" | "no_match" | "needs_attention" | "already_scanned"
    purchase_order: str
    inventory_id: str
    serial: str = ""  # serial number scanned with the physical unit
    brand: str = ""  # brand from the inventory catalog
    vendor: str = ""  # vendor from the inventory catalog
    tags: str = ""  # tags from the inventory catalog


def validate_record(data: dict) -> list[str]:
    """Return a list of problem strings; empty list means valid."""
    problems: list[str] = []

    for field in _STR_FIELDS:
        if field not in data or data[field] is None:
            problems.append(f"{field}: missing required field")
        elif not isinstance(data[field], str):
            problems.append(f"{field}: expected str, got {type(data[field]).__name__}")
        elif field == "receiving_id" and not data[field].strip():
            problems.append("receiving_id: must be non-empty")
        elif field == "match_status" and data[field] not in _VALID_MATCH_STATUSES:
            problems.append(
                f"match_status: '{data['match_status']}' is not one of "
                f"{sorted(_VALID_MATCH_STATUSES)}"
            )

    for field in _OPTIONAL_STR_FIELDS:
        if field in data and data[field] is not None and not isinstance(data[field], str):
            problems.append(f"{field}: expected str or None, got {type(data[field]).__name__}")

    ts = data.get("timestamp")
    if isinstance(ts, str) and ts.strip():
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            problems.append(f"timestamp: '{ts}' is not valid ISO-8601")

    qty = data.get("quantity")
    if qty is None:
        problems.append("quantity: missing required field")
    elif isinstance(qty, bool) or not isinstance(qty, int):
        problems.append(f"quantity: expected positive int, got {type(qty).__name__}")
    elif qty < 1:
        problems.append(f"quantity: must be a positive integer, got {qty}")

    ps = data.get("product_size")
    if ps is None:
        problems.append("product_size: missing required field")
    elif not isinstance(ps, dict):
        problems.append(f"product_size: expected dict with w/d/h, got {type(ps).__name__}")
    else:
        for dim in ("w", "d", "h"):
            if dim not in ps:
                problems.append(f"product_size: missing key '{dim}'")
            elif isinstance(ps[dim], bool) or not isinstance(ps[dim], int | float):
                problems.append(
                    f"product_size[{dim}]: expected numeric, got {type(ps[dim]).__name__}"
                )
            elif ps[dim] < 0:
                problems.append(f"product_size[{dim}]: must be >= 0, got {ps[dim]}")

    return problems


def migrate(data: dict) -> dict:
    """Upgrade data dict to the current schema version.

    v1 → v2: add empty defaults for serial, brand, vendor, tags if absent.
    """
    for field in _OPTIONAL_STR_FIELDS:
        if field not in data:
            data = {**data, field: ""}
    return data


def from_dict(data: dict) -> ReceivingRecord:
    """Build a ReceivingRecord from a dict. Raises ValidationError on any problem."""
    data = migrate(data)
    problems = validate_record(data)
    if problems:
        raise ValidationError("Record failed validation:\n" + "\n".join(f"  {p}" for p in problems))
    return ReceivingRecord(
        truck=data["truck"],
        stop=data["stop"],
        sales_order=data["sales_order"],
        model_number=data["model_number"],
        product_category=data["product_category"],
        product_size=dict(data["product_size"]),
        quantity=data["quantity"],
        receiving_id=data["receiving_id"],
        timestamp=data["timestamp"],
        match_status=data["match_status"],
        purchase_order=data["purchase_order"],
        inventory_id=data["inventory_id"],
        serial=data.get("serial") or "",
        brand=data.get("brand") or "",
        vendor=data.get("vendor") or "",
        tags=data.get("tags") or "",
    )


def to_dict(record: ReceivingRecord) -> dict:
    """Serialize a ReceivingRecord to a plain dict."""
    return asdict(record)
