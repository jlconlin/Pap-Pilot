"""Guarded, read-only access to a supported OSCAR SQLite database."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Final


SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({17})


class OscarDatabaseError(RuntimeError):
    """Base class for failures that prevent safe OSCAR database access."""


class OscarDatabaseOpenError(OscarDatabaseError):
    """Raised when SQLite cannot open the database explicitly read-only."""


class MissingSchemaVersionError(OscarDatabaseError):
    """Raised when the database has no readable OSCAR schema version."""


class UnsupportedSchemaVersionError(OscarDatabaseError):
    """Raised when the database schema is not explicitly supported."""

    def __init__(self, schema_version: object) -> None:
        supported = ", ".join(
            str(version) for version in sorted(SUPPORTED_SCHEMA_VERSIONS)
        )
        super().__init__(
            f"Unsupported OSCAR schema version {schema_version!r}; "
            f"supported version: {supported}."
        )
        self.schema_version = schema_version


@contextmanager
def open_oscar_database(
    database_path: str | Path,
) -> Iterator[sqlite3.Connection]:
    """Open and validate an OSCAR database without permitting writes.

    The caller must keep OSCAR closed and use a backup or disposable database
    until concurrent-read safety is separately verified.
    """

    resolved_path = Path(database_path).expanduser().resolve()
    database_uri = f"{resolved_path.as_uri()}?mode=ro"

    try:
        connection = sqlite3.connect(database_uri, uri=True)
    except sqlite3.Error as error:
        raise OscarDatabaseOpenError(
            "Unable to open the OSCAR database in read-only mode."
        ) from error

    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        schema_version = _read_schema_version(connection)
        if (
            type(schema_version) is not int
            or schema_version not in SUPPORTED_SCHEMA_VERSIONS
        ):
            raise UnsupportedSchemaVersionError(schema_version)
        yield connection
    finally:
        connection.close()


def _read_schema_version(connection: sqlite3.Connection) -> object:
    try:
        row = connection.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
    except sqlite3.DatabaseError as error:
        raise MissingSchemaVersionError(
            "The OSCAR database has no readable schema_version.version value."
        ) from error

    if row is None or row[0] is None:
        raise MissingSchemaVersionError(
            "The OSCAR database has no readable schema_version.version value."
        )
    return row[0]
