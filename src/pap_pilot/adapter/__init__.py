"""Read-only adapters for external PAP data sources."""

from pap_pilot.adapter.oscar import (
    MissingSchemaVersionError,
    OscarDatabaseError,
    OscarDatabaseOpenError,
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
    open_oscar_database,
)
from pap_pilot.adapter.session_summary import (
    InvalidSessionSummaryError,
    OscarMachineProvenance,
    OscarProfileProvenance,
    OscarSchemaProvenance,
    OscarSessionBoundaries,
    OscarSessionSettings,
    OscarSessionSummary,
    OscarSettingSource,
    REQUIRED_SETTING_CODES,
    SessionNotFoundError,
    SessionSummaryError,
    extract_session_summary,
)

__all__ = [
    "MissingSchemaVersionError",
    "InvalidSessionSummaryError",
    "OscarMachineProvenance",
    "OscarProfileProvenance",
    "OscarSchemaProvenance",
    "OscarSessionBoundaries",
    "OscarSessionSettings",
    "OscarSessionSummary",
    "OscarSettingSource",
    "OscarDatabaseError",
    "OscarDatabaseOpenError",
    "SUPPORTED_SCHEMA_VERSIONS",
    "REQUIRED_SETTING_CODES",
    "SessionNotFoundError",
    "SessionSummaryError",
    "UnsupportedSchemaVersionError",
    "open_oscar_database",
    "extract_session_summary",
]
