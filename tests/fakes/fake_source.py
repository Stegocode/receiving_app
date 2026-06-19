"""
Owns: fixture-based PurchaseOrderSource fake for use in tests.
Must not: perform any network or scraper calls.
May import: core.ports.
"""
# Owns: fixture-based PurchaseOrderSource fake for use in tests.
# Must not: perform any network or scraper calls.
# May import: core.ports.

from __future__ import annotations


class FakePurchaseOrderSource:
    """In-memory PurchaseOrderSource backed by a pre-loaded fixture dict.

    fixture maps po_number -> list of item dicts.
    fetch_order returns the fixture rows for a known po_number, [] for unknown.
    fetch_all_open_orders returns every row across all POs.
    """

    def __init__(self, fixture: dict[str, list[dict]]) -> None:
        self._fixture = fixture

    def fetch_order(self, po_number: str) -> list[dict]:
        return list(self._fixture.get(po_number, []))

    def fetch_all_open_orders(self) -> list[dict]:
        result: list[dict] = []
        for rows in self._fixture.values():
            result.extend(rows)
        return result
