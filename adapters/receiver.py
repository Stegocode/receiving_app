# Owns: PortalReceiver, FakeReceiver, make_receiver().
# Must not: import services or other adapters; must not read environment variables directly.
# May import: core.errors, core.matching, core.ports (ReceiveOutcome),
#             playwright, logging, time, pathlib.
#
# PortalReceiver is PORTED but live-untested — see DEBT.md [DEBT-T13-001].

from __future__ import annotations

import logging
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

from playwright.sync_api import (
    Browser,
    BrowserContext,
    ElementHandle,
    Page,
    Playwright,
    sync_playwright,
)

from core.errors import ExecutorError
from core.matching import match_score, normalize
from core.ports import ReceiveOutcome

_log = logging.getLogger(__name__)

# Timing constants (seconds) — require live validation against the portal.
_NAV_SETTLE_SECS = 2.0
_LOCATION_SETTLE_SECS = 3.0
_WHSE_SETTLE_SECS = 1.5
_QTY_SETTLE_SECS = 0.5
_SERIAL_SETTLE_SECS = 0.5
_REVIEW_SETTLE_SECS = 2.0
_FINALIZE_SETTLE_SECS = 3.0
_GRID_PAGE_SETTLE_SECS = 1.5

# Grid column positions (confirmed from live screenshots, June 2026).
_MODEL_COL = 3
_TBR_COL = 7
_QTY_COL = 8

_GRID_ROW_TIMEOUT_MS = 8_000
_RECEIVE_URL_TIMEOUT_MS = 15_000
_MAX_GRID_PAGES = 10

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_NEXT_BTN_SELECTOR = (
    ".k-pager-wrap a.k-next-button, "
    ".k-grid-pager a[aria-label*='next' i], "
    ".k-grid-pager .k-i-arrow-e"
)

# Inline JS — portal-specific; none are domain names or credentials.
_READ_OPTIONS_JS = (
    "(sel) => { const s=document.querySelector(sel); if(!s) return [];"
    " return Array.from(s.options).map(o=>({value:o.value,text:o.text})); }"
)
_KENDO_SET_JS = (
    "(a) => { const s=document.querySelector(a.selector); if(!s) return; s.value=a.value;"
    " if(typeof $!=='undefined'){const w=$(s).data('kendoDropDownList');"
    " if(w){w.value(a.value);w.trigger('change');return;}}"
    " s.dispatchEvent(new Event('change',{bubbles:true})); }"
)
_QTY_SET_JS = "el=>{el.value='1';el.dispatchEvent(new Event('change',{bubbles:true}));}"
_FINALIZE_CHECK_JS = (
    "()=>{const as=document.querySelectorAll('.alert-danger,.alert.alert-error');"
    " for(const a of as) if(a.offsetParent!==null&&(a.textContent||'').trim().length>0)"
    " return a.textContent.trim(); return '';}"
)


def _model_matches(target: str, cell_text: str) -> bool:
    """True if target and cell_text refer to the same model (fuzzy, space-collapsed, >= 0.85)."""
    a = normalize(target)
    b = normalize(cell_text)
    if not a or not b:
        return False
    if a == b or b in a or a in b:
        return True
    a_c = a.replace(" ", "")
    b_c = b.replace(" ", "")
    if a_c == b_c or b_c in a_c or a_c in b_c:
        return True
    return match_score(a_c, b_c) >= 0.85


class PortalReceiver:
    """Portal receiving wizard executor (Playwright sync, PORTED/live-untested)."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        location_label: str,
        whse_label: str,
        screenshot_dir: Path,
        headless: bool = True,
    ) -> None:
        self._base_url = base_url
        self._username = username
        self._password = password
        self._location_label = location_label
        self._whse_label = whse_label
        self._screenshot_dir = screenshot_dir
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _screenshot(self, page: Page, step: str, inventory_id: str) -> None:
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        with suppress(Exception):
            page.screenshot(path=str(self._screenshot_dir / f"{inventory_id}_{step}.png"))

    def _login(self, page: Page) -> None:
        page.goto(self._base_url + "/login")
        page.wait_for_load_state("networkidle")
        page.fill("input[name='email']", self._username)
        page.fill("input[name='password']", self._password)
        page.press("input[name='password']", "Enter")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        _log.info("receiver.login.complete")

    def _ensure_session(self) -> Page:
        if self._page is not None:
            return self._page
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context(
                user_agent=_USER_AGENT, viewport={"width": 1920, "height": 1080}
            )
            self._page = self._context.new_page()
            self._login(self._page)
        except Exception:
            self.close()
            raise
        return self._page

    def close(self) -> None:
        """Release the browser session. Safe to call when no browser was opened."""
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _find_model_row(self, page: Page, model: str) -> ElementHandle | None:
        """Scan the Kendo grid (paginated, up to _MAX_GRID_PAGES) for model with TBR > 0."""
        try:
            page.wait_for_selector("tr.k-master-row", timeout=_GRID_ROW_TIMEOUT_MS)
        except Exception:
            _log.warning("receiver.grid.no_rows model=%s", model)
        for _ in range(_MAX_GRID_PAGES):
            for row in page.query_selector_all("tr.k-master-row"):
                cells = row.query_selector_all("td")
                if len(cells) <= _MODEL_COL:
                    continue
                model_text = (cells[_MODEL_COL].inner_text() or "").strip()
                if not _model_matches(model, model_text):
                    continue
                tbr = 0
                if len(cells) > _TBR_COL:
                    with suppress(ValueError, TypeError):
                        tbr = int((cells[_TBR_COL].inner_text() or "").strip())
                if tbr > 0:
                    _log.info("receiver.grid.matched model=%s tbr=%d", model_text, tbr)
                    return row
            try:
                nxt = page.locator(_NEXT_BTN_SELECTOR).first
                if not nxt.is_visible(timeout=1000):
                    break
            except Exception:
                break
            if "k-disabled" in (nxt.get_attribute("class") or ""):
                break
            if (nxt.get_attribute("aria-disabled") or "").lower() == "true":
                break
            nxt.click()
            time.sleep(_GRID_PAGE_SETTLE_SECS)
        return None

    def _step1_navigate(
        self, page: Page, po_number: str, inventory_id: str
    ) -> ReceiveOutcome | None:
        page.goto(f"{self._base_url}/purchase-orders?id={po_number}")
        page.wait_for_load_state("networkidle")
        time.sleep(_NAV_SETTLE_SECS)
        if "/login" in page.url:
            _log.info("receiver.relogin")
            self._login(page)
        if "/login" in page.url:
            page.goto(f"{self._base_url}/purchase-orders?id={po_number}")
            page.wait_for_load_state("networkidle")
            time.sleep(_NAV_SETTLE_SECS)
        page.click("a#receive-btn")
        try:
            page.wait_for_url(
                f"**/purchase-orders/{po_number}/receiving**",
                timeout=_RECEIVE_URL_TIMEOUT_MS,
            )
        except Exception:
            _log.warning("step1.no_url", extra={"po": po_number, "inv": inventory_id})
            return "not_found"
        page.wait_for_load_state("networkidle")
        time.sleep(_NAV_SETTLE_SECS)
        self._screenshot(page, "01_receiving_page", inventory_id)
        return None

    def _step2_set_location(self, page: Page, inventory_id: str) -> None:
        options = page.evaluate(_READ_OPTIONS_JS, "select.apply-all-location")
        loc_value = ""
        for opt in options or []:
            if self._location_label in str(opt.get("text", "")):
                loc_value = str(opt["value"])
                break
        if not loc_value:
            _log.warning("step2.no_location", extra={"label": self._location_label})
        page.evaluate(_KENDO_SET_JS, {"selector": "select.apply-all-location", "value": loc_value})
        page.click("button[onclick='onApplyAllLocation(0)']")
        time.sleep(_LOCATION_SETTLE_SECS)
        self._screenshot(page, "02_location_applied", inventory_id)

    def _step3_set_whse(self, page: Page, inventory_id: str) -> None:
        options = page.evaluate(_READ_OPTIONS_JS, "select.apply-all-whse")
        _log.info("step3.whse_options", extra={"options": options})
        whse_value = ""
        for opt in options or []:
            if self._whse_label in str(opt.get("text", "")):
                whse_value = str(opt["value"])
                break
        if not whse_value:
            _log.warning("step3.no_whse", extra={"label": self._whse_label})
        page.evaluate(_KENDO_SET_JS, {"selector": "select.apply-all-whse", "value": whse_value})
        page.click("button[onclick='onApplyAllWhseLocation(0)']")
        time.sleep(_WHSE_SETTLE_SECS)
        self._screenshot(page, "03_whse_applied", inventory_id)

    def _step4_find_row(
        self, page: Page, po_number: str, inventory_id: str, model: str
    ) -> ReceiveOutcome | None:
        _log.info("step4.search", extra={"po": po_number, "model": model, "inv": inventory_id})
        self._screenshot(page, "04a_grid_before_search", inventory_id)
        row = self._find_model_row(page, model)
        if row is None:
            _log.warning("step4.no_row", extra={"model": model, "inv": inventory_id})
            return "not_found"
        qty_input = row.query_selector("input.receiving-qty-input")
        if qty_input is None:
            cells = row.query_selector_all("td")
            if len(cells) > _QTY_COL:
                qty_input = cells[_QTY_COL].query_selector("input")
        if qty_input is None:
            _log.warning("step4.no_qty_input", extra={"model": model, "inv": inventory_id})
            return "not_found"
        page.evaluate(_QTY_SET_JS, qty_input)
        time.sleep(_QTY_SETTLE_SECS)
        self._screenshot(page, "04_qty_set", inventory_id)
        return None

    def _step6_enter_serial(
        self, page: Page, inventory_id: str, serial: str
    ) -> ReceiveOutcome | None:
        serial_input = page.query_selector("input.brand-serial-input")
        if serial_input is None:
            _log.warning("step6.no_serial_input", extra={"inv": inventory_id})
            return "not_found"
        serial_input.fill(serial)
        time.sleep(_SERIAL_SETTLE_SECS)
        self._screenshot(page, "06_serial_entered", inventory_id)
        return None

    def _step8_finalize(self, page: Page, inventory_id: str) -> ReceiveOutcome:
        page.click("a[href='#finish']")
        time.sleep(_FINALIZE_SETTLE_SECS)
        self._screenshot(page, "08_finalized", inventory_id)
        error_text = page.evaluate(_FINALIZE_CHECK_JS)
        if error_text:
            _log.warning(
                "step8.finalize_error",
                extra={"inv": inventory_id, "detail": str(error_text)[:300]},
            )
            return "finalize_error"
        _log.info("step8.received", extra={"inv": inventory_id})
        return "received"

    def _run_wizard(
        self, page: Page, po_number: str, inventory_id: str, model: str, serial: str
    ) -> ReceiveOutcome:
        outcome = self._step1_navigate(page, po_number, inventory_id)
        if outcome is not None:
            return outcome
        self._step2_set_location(page, inventory_id)
        self._step3_set_whse(page, inventory_id)
        outcome = self._step4_find_row(page, po_number, inventory_id, model)
        if outcome is not None:
            return outcome
        page.click("a[href='#next']")
        time.sleep(_REVIEW_SETTLE_SECS)
        self._screenshot(page, "05_serial_page", inventory_id)
        outcome = self._step6_enter_serial(page, inventory_id, serial)
        if outcome is not None:
            return outcome
        page.click("a[href='#next']")
        time.sleep(_REVIEW_SETTLE_SECS)
        self._screenshot(page, "07_review_page", inventory_id)
        return self._step8_finalize(page, inventory_id)

    def receive_item(
        self, po_number: str, inventory_id: str, model: str, serial: str
    ) -> ReceiveOutcome:
        """Run the portal receiving wizard; return "received", "not_found", or "finalize_error"."""
        t0 = time.monotonic()
        _log.info("receiver.item.start", extra={"po": po_number, "inv": inventory_id})
        try:
            page = self._ensure_session()
            outcome = self._run_wizard(page, po_number, inventory_id, model, serial)
            dur_ms = int((time.monotonic() - t0) * 1000)
            _log.info("receiver.item.done inv=%s outcome=%s ms=%d", inventory_id, outcome, dur_ms)
            return outcome
        except ExecutorError:
            raise
        except Exception as exc:
            raise ExecutorError(
                f"Unexpected failure receiving inv={inventory_id!r}: {exc!r}"
            ) from exc


class FakeReceiver:
    """In-memory ReceivingExecutor; outcomes keyed by inventory_id; "raise" → ExecutorError."""

    def __init__(
        self, outcomes: dict[str, str] | None = None, default_outcome: ReceiveOutcome = "received"
    ) -> None:
        self.outcomes: dict[str, str] = dict(outcomes or {})
        self.default_outcome: ReceiveOutcome = default_outcome
        self.calls: list[tuple[str, str, str, str]] = []
        self.closed = False

    def receive_item(
        self, po_number: str, inventory_id: str, model: str, serial: str
    ) -> ReceiveOutcome:
        self.calls.append((po_number, inventory_id, model, serial))
        configured = self.outcomes.get(inventory_id)
        if configured is None:
            return self.default_outcome
        if configured == "raise":
            raise ExecutorError(f"FakeReceiver configured to raise for inv={inventory_id!r}")
        return cast(ReceiveOutcome, configured)

    def close(self) -> None:
        self.closed = True


def make_receiver(
    receiver_type: str,
    base_url: str = "",
    username: str = "",
    password: str = "",
    location_label: str = "",
    whse_label: str = "",
    screenshot_dir: Path | None = None,
    headless: bool = True,
    outcomes: dict[str, str] | None = None,
    default_outcome: ReceiveOutcome = "received",
) -> PortalReceiver | FakeReceiver:
    """Construct a ReceivingExecutor. Raises ExecutorError for unknown types (portal, fake)."""
    if receiver_type == "fake":
        return FakeReceiver(outcomes, default_outcome)
    if receiver_type == "portal":
        return PortalReceiver(
            base_url=base_url,
            username=username,
            password=password,
            location_label=location_label,
            whse_label=whse_label,
            screenshot_dir=screenshot_dir or Path("screenshots"),
            headless=headless,
        )
    raise ExecutorError(
        f"Unknown RECEIVER_TYPE {receiver_type!r} — supported values: portal, fake. "
        "Set RECEIVER_TYPE in .env and restart."
    )
