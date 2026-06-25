"""
Owns: PurchaseOrderSource implementations — PortalSource (live portal scraper),
      FakeSource (JSON fixture for dev/test mode), and make_source() factory.
Must not: import services, adapters.db, or adapters.sink; must not read
          environment variables directly (credentials injected via constructor).
May import: core.errors, selenium, csv, json, logging, pathlib, time.

Credentials are injected at construction time so this module never holds
credential env-var names as literals — see config.py for the wiring point.

PortalSource is PORTED but live-untested: the real scrape cannot run in CI.
FakeSource reads a local JSON file (FAKE_SOURCE_DATA) for dev mode.
See DEBT.md for live-testing entries.
"""
# Owns: PortalSource, FakeSource, make_source().
# Must not: import services, adapters.db, adapters.sink; no direct env-var reads.
# May import: core.errors, selenium, csv, json, logging, pathlib, time.

from __future__ import annotations

import csv
import json
import logging
import time
from contextlib import suppress
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.errors import SourceError

_log = logging.getLogger(__name__)

# Timing constants (seconds) — ported from oracle; require live validation.
_WAIT_TIMEOUT_SECS = 40
_LOGIN_SETTLE_SECS = 8
_POST_LOGIN_SECS = 4
_POPUP_DISMISS_SECS = 3
_FILTER_SETTLE_SECS = 8
_NAV_SETTLE_SECS = 5
_FILTER_UNCHECK_SECS = 2
_DOWNLOAD_TIMEOUT_SECS = 60
_DOWNLOAD_FALLBACK_SECS = 20


# ── Browser helpers ───────────────────────────────────────────────────────────


def _resolve_service() -> Service | None:
    """Locate the newest local chromedriver binary, or None for auto-detection."""
    cache = Path.home() / ".cache" / "selenium" / "chromedriver" / "win64"
    if not cache.exists():
        return None
    versions = sorted(
        (p for p in cache.iterdir() if p.is_dir() and (p / "chromedriver.exe").exists()),
        key=lambda p: tuple(int(x) for x in p.name.split(".") if x.isdigit()),
    )
    return Service(executable_path=str(versions[-1] / "chromedriver.exe")) if versions else None


def _build_driver(download_dir: Path) -> webdriver.Chrome:
    """Build a headless Chrome instance configured to download to download_dir."""
    download_str = str(download_dir)
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_str,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    svc = _resolve_service()
    return webdriver.Chrome(service=svc, options=opts) if svc else webdriver.Chrome(options=opts)


def _login(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    base_url: str,
    username: str,
    password: str,
) -> None:
    """Authenticate to the order management portal."""
    try:
        driver.get(base_url + "/login")
        time.sleep(_LOGIN_SETTLE_SECS)
        wait.until(EC.presence_of_element_located((By.NAME, "email")))
        driver.find_element(By.NAME, "email").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(_POST_LOGIN_SECS)
        # Dismiss the location-save prompt if it appears — expected absent sometimes.
        try:
            save_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "save-current-location"))
            )
            driver.execute_script("arguments[0].click();", save_btn)
            time.sleep(_POPUP_DISMISS_SECS)
        except TimeoutException:
            pass  # prompt absent — continue
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("portal login failed") from exc


def _apply_on_order_filter(driver: webdriver.Chrome, wait: WebDriverWait, base_url: str) -> None:
    """Navigate to serial inventory and apply the on-order filter."""
    try:
        driver.get(base_url + "/inventory/serial")
        time.sleep(_NAV_SETTLE_SECS)
        # Uncheck the open-items filter (on by default; includes already-received units).
        open_cb = wait.until(EC.presence_of_element_located((By.ID, "OpenFilter")))
        if open_cb.is_selected():
            driver.execute_script("arguments[0].click();", open_cb)
            time.sleep(_FILTER_UNCHECK_SECS)
        # Check the on-order filter.
        order_cb = wait.until(EC.presence_of_element_located((By.ID, "OnOrderFilter")))
        if not order_cb.is_selected():
            driver.execute_script("arguments[0].click();", order_cb)
            time.sleep(_FILTER_SETTLE_SECS)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("failed to apply on-order filter") from exc


def _trigger_export(driver: webdriver.Chrome) -> None:
    """Click the spreadsheet export button."""
    try:
        export_btn = driver.find_element(By.XPATH, "//i[contains(@class,'fa-file-excel-o')]/..")
        driver.execute_script("arguments[0].click();", export_btn)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("failed to trigger export") from exc


def _wait_for_csv(download_dir: Path) -> Path:
    """Poll download_dir for the exported inventory CSV; raise SourceError on timeout."""
    for keyword, timeout in [
        ("serial-number-inventory", _DOWNLOAD_TIMEOUT_SECS),
        (".csv", _DOWNLOAD_FALLBACK_SECS),
    ]:
        for _ in range(timeout):
            try:
                matches = [
                    f
                    for f in download_dir.iterdir()
                    if keyword in f.name.lower() and not f.name.endswith(".crdownload")
                ]
            except OSError as exc:
                raise SourceError(f"download directory unreadable — {download_dir}") from exc
            if matches:
                return matches[0]
            time.sleep(1)
    raise SourceError(f"export timed out — no CSV found in {download_dir}")


def _guard_download_dir(path: Path) -> None:
    """Raise SourceError if path is unsafe for bulk-deletion of export files.

    Rejects the user home directory, the filesystem root, and any path that is
    its own parent. Must be called with a resolved (absolute) path.
    """
    home = Path.home().resolve()
    root = Path("/").resolve()
    if path in (home, root) or path.parent == path:
        raise SourceError(
            f"DOWNLOAD_DIR {str(path)!r} failed the safety check — "
            "it must not be the home directory or filesystem root. "
            "Configure a dedicated download subdirectory."
        )


def _parse_on_order_csv(csv_path: Path) -> list[dict]:
    """Parse the on-order inventory CSV. Returns list of row dicts."""
    try:
        rows: list[dict] = []
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                inv_id = str(row.get("Inventory Id", "") or "").strip()
                if not inv_id:
                    continue
                description = (
                    str(row.get("Category", "") or row.get("Product Group", "") or "").strip()
                    or None
                )
                rows.append(
                    {
                        "inventory_id": inv_id,
                        "purchase_order": str(row.get("PO #", "") or "").strip(),
                        "model_number": str(row.get("Model", "") or "").strip(),
                        "description": description,
                        "brand": str(row.get("Brand", "") or "").strip() or None,
                        "vendor": None,
                        "tags": str(row.get("Tags", "") or "").strip() or None,
                    }
                )
        return rows
    except (OSError, csv.Error) as exc:
        raise SourceError(f"failed to parse inventory CSV — {csv_path.name}") from exc


# ── Adapter ───────────────────────────────────────────────────────────────────


class PortalSource:
    """PurchaseOrderSource backed by the order management portal scraper.

    Credentials and paths are injected at construction time — this class never
    reads environment variables directly and never holds the env-var names as literals.
    Wire it in the entry point using the SOURCE_BASE_URL, credential, and
    DOWNLOAD_DIR attributes from config — see config.py for the full list.

    PORTED but live-untested in CI. See DEBT.md [DEBT-T08-*] for items that
    require validation against the live portal.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        download_dir: Path,
    ) -> None:
        self._base_url = base_url
        self._username = username
        self._password = password
        self._download_dir = download_dir

    def fetch_order(self, po_number: str) -> list[dict]:
        """Fetch open-order rows for a single PO number."""
        t0 = time.monotonic()
        _log.info(
            "portal.fetch_order.start",
            extra={"event": "fetch_order.start", "po_number": po_number},
        )
        all_rows = self._fetch_all()
        result = [r for r in all_rows if r.get("purchase_order") == po_number]
        dur_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "portal.fetch_order.complete",
            extra={
                "event": "fetch_order.complete",
                "po_number": po_number,
                "rows": len(result),
                "duration_ms": dur_ms,
            },
        )
        return result

    def fetch_all_open_orders(self) -> list[dict]:
        """Fetch all open-order rows from the portal."""
        t0 = time.monotonic()
        _log.info(
            "portal.fetch_all.start",
            extra={"event": "fetch_all.start"},
        )
        result = self._fetch_all()
        dur_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "portal.fetch_all.complete",
            extra={"event": "fetch_all.complete", "rows": len(result), "duration_ms": dur_ms},
        )
        return result

    def _fetch_all(self) -> list[dict]:
        """Scrape the full on-order inventory CSV and return parsed rows."""
        dl = self._download_dir.resolve()
        _guard_download_dir(dl)
        dl.mkdir(parents=True, exist_ok=True)
        # Clear only expected export files — pattern-scoped so unrelated files
        # in DOWNLOAD_DIR are not deleted if the path is misconfigured.
        for f in dl.iterdir():
            if f.is_file() and f.suffix.lower() in {".csv", ".crdownload"}:
                with suppress(OSError):
                    f.unlink()

        try:
            driver = _build_driver(dl)
        except Exception as exc:
            raise SourceError("failed to launch browser") from exc

        wait = WebDriverWait(driver, _WAIT_TIMEOUT_SECS)
        try:
            _login(driver, wait, self._base_url, self._username, self._password)
            _apply_on_order_filter(driver, wait, self._base_url)
            _trigger_export(driver)
            csv_path = _wait_for_csv(dl)
            return _parse_on_order_csv(csv_path)
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError("order portal scrape failed") from exc
        finally:
            driver.quit()


# ── Dev-mode fake ─────────────────────────────────────────────────────────────


class FakeSource:
    """PurchaseOrderSource backed by a local JSON fixture file.

    Used in dev/test mode (SOURCE_TYPE=fake). The file is a JSON array of
    line-item dicts whose shape matches PortalSource's fetch_order output.
    Loaded lazily on the first call; cached for the lifetime of the instance.
    """

    def __init__(self, data_path: Path) -> None:
        self._data_path = data_path
        self._rows: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._rows is None:
            try:
                self._rows = json.loads(self._data_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SourceError(
                    f"fake source data unreadable — {self._data_path}. "
                    "Check FAKE_SOURCE_DATA in .env."
                ) from exc
        return self._rows

    def fetch_order(self, po_number: str) -> list[dict]:
        t0 = time.monotonic()
        _log.info(
            "fake.fetch_order.start",
            extra={"event": "fetch_order.start", "po_number": po_number},
        )
        rows = [r for r in self._load() if r.get("purchase_order") == po_number]
        dur_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "fake.fetch_order.complete",
            extra={
                "event": "fetch_order.complete",
                "po_number": po_number,
                "rows": len(rows),
                "duration_ms": dur_ms,
            },
        )
        return rows

    def fetch_all_open_orders(self) -> list[dict]:
        t0 = time.monotonic()
        _log.info("fake.fetch_all.start", extra={"event": "fetch_all.start"})
        result = list(self._load())
        dur_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "fake.fetch_all.complete",
            extra={"event": "fetch_all.complete", "rows": len(result), "duration_ms": dur_ms},
        )
        return result


# ── Factory ───────────────────────────────────────────────────────────────────


def make_source(
    source_type: str,
    base_url: str,
    username: str,
    password: str,
    download_dir: Path,
    fake_data_path: Path | None = None,
) -> PortalSource | FakeSource:
    """Construct a PurchaseOrderSource from a type string.

    Raises SourceError for unknown source_type values, before constructing anything.
    """
    if source_type == "portal":
        return PortalSource(base_url, username, password, download_dir)
    if source_type == "fake":
        return FakeSource(fake_data_path or Path("test_data/pos.json"))
    raise SourceError(
        f"Unknown SOURCE_TYPE '{source_type}' — supported values: portal, fake. "
        "Set SOURCE_TYPE in .env and restart."
    )
