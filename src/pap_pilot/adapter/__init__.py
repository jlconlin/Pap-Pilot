"""Read-only adapters for external PAP data sources."""

from pap_pilot.adapter.oscar import (
    MissingSchemaVersionError,
    OscarDatabaseError,
    OscarDatabaseOpenError,
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
    open_oscar_database,
)

__all__ = [
    "MissingSchemaVersionError",
    "OscarDatabaseError",
    "OscarDatabaseOpenError",
    "SUPPORTED_SCHEMA_VERSIONS",
    "UnsupportedSchemaVersionError",
    "open_oscar_database",
]
