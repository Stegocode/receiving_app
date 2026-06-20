"""
Owns: typed error taxonomy for the entire application.
Must not: import anything outside stdlib.
May import: stdlib only.
"""
# Owns: typed error taxonomy for the entire application.
# Must not: import anything outside stdlib.
# May import: stdlib only.


class ReceivingAppError(Exception):
    """Base for all application errors. Subclass; never raise directly."""


class ConfigError(ReceivingAppError):
    """Missing or invalid configuration.

    Raised only by config.validate(). Message lists every missing/invalid var
    with an actionable description — fix these in .env before starting.
    """


class ValidationError(ReceivingAppError):
    """Record failed schema validation.

    Constraint violated — one or more fields are missing, wrong type, or out
    of range — fix the data before saving or emitting the record.
    """


class SourceError(ReceivingAppError):
    """PurchaseOrderSource adapter failure.

    Network or parse failure fetching purchase order data — check source
    credentials in config and retry; original exception is chained.
    """


class SinkError(ReceivingAppError):
    """ResultSink adapter failure.

    API call to the result sink failed — check SINK_API_TOKEN and
    SINK_BOARD_ID in config and retry; original exception is chained.
    """


class RepositoryError(ReceivingAppError):
    """SQLite Repository adapter failure.

    Database operation failed or a required row was not found — check
    DB_PATH in config and inspect the database file; original exception
    is chained where applicable.
    """


class SyncKillError(ReceivingAppError):
    """Sync loop aborted — error rate exceeded KILL_THRESHOLD.

    Too many items failed in a single sync pass — success rate dropped below
    the kill threshold. Investigate sink/source errors before retrying.
    """


class PrinterError(ReceivingAppError):
    """Label printer failure.

    Raised when print_label fails — check the printer connection and paper
    supply. The record is already saved and can be re-printed.
    """


class ScannerError(ReceivingAppError):
    """Scanner adapter failure.

    Raised by make_scanner when an unknown scanner_type is requested — set
    SCANNER_TYPE to a supported value (wedge, manual) in .env and restart.
    """
