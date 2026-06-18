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


# T-04 adds: ValidationError, SourceError, SinkError, RepositoryError, SyncKillError.
