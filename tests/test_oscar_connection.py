"""Focused tests for guarded OSCAR database access."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pap_pilot.adapter import (
    MissingSchemaVersionError,
    OscarDatabaseOpenError,
    UnsupportedSchemaVersionError,
    open_oscar_database,
)


class OscarConnectionTests(unittest.TestCase):
    """Exercise only synthetic databases created for each test."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "oscar.db"

    def _create_database(
        self,
        *,
        schema_version: int | None = 17,
        include_schema_table: bool = True,
    ) -> bytes:
        with closing(sqlite3.connect(self.database_path)) as connection:
            if include_schema_table:
                connection.execute(
                    "CREATE TABLE schema_version (version INTEGER NOT NULL)"
                )
                if schema_version is not None:
                    connection.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (schema_version,),
                    )
            connection.execute(
                "CREATE TABLE sentinel (value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO sentinel (value) VALUES ('unchanged')"
            )
            connection.commit()
        return self.database_path.read_bytes()

    def test_supported_database_allows_reads_and_rejects_writes(self) -> None:
        original_database = self._create_database()

        with open_oscar_database(self.database_path) as connection:
            value = connection.execute(
                "SELECT value FROM sentinel"
            ).fetchone()
            self.assertEqual(value, ("unchanged",))
            self.assertEqual(
                connection.execute("PRAGMA query_only").fetchone(),
                (1,),
            )
            self.assertTrue(connection.in_transaction)

            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "CREATE TEMP TABLE forbidden (value INTEGER)"
                )

            connection.execute("PRAGMA query_only = OFF")
            self.assertEqual(
                connection.execute("PRAGMA query_only").fetchone(),
                (0,),
            )
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute(
                    "INSERT INTO sentinel (value) VALUES ('changed')"
                )

        self.assertEqual(self.database_path.read_bytes(), original_database)
        with closing(
            sqlite3.connect(self.database_path)
        ) as verification_connection:
            row_count = verification_connection.execute(
                "SELECT COUNT(*) FROM sentinel"
            ).fetchone()
        self.assertEqual(row_count, (1,))
        self.assertEqual(
            list(self.database_path.parent.iterdir()),
            [self.database_path],
        )

    def test_missing_database_is_not_created(self) -> None:
        self.assertFalse(self.database_path.exists())

        with self.assertRaises(OscarDatabaseOpenError):
            with open_oscar_database(self.database_path):
                self.fail("missing database must not be created or exposed")

        self.assertFalse(self.database_path.exists())

    def test_unsupported_schema_versions_fail_without_changes(self) -> None:
        for schema_version in (16, 18):
            with self.subTest(schema_version=schema_version):
                original_database = self._create_database(
                    schema_version=schema_version
                )

                with self.assertRaises(UnsupportedSchemaVersionError) as raised:
                    with open_oscar_database(self.database_path):
                        self.fail("unsupported database must not be exposed")

                self.assertEqual(
                    raised.exception.schema_version,
                    schema_version,
                )
                self.assertEqual(
                    self.database_path.read_bytes(),
                    original_database,
                )
                self.database_path.unlink()

    def test_missing_schema_table_fails_without_changes(self) -> None:
        original_database = self._create_database(include_schema_table=False)

        with self.assertRaises(MissingSchemaVersionError):
            with open_oscar_database(self.database_path):
                self.fail("database without schema metadata must not be exposed")

        self.assertEqual(self.database_path.read_bytes(), original_database)

    def test_empty_schema_table_fails_without_changes(self) -> None:
        original_database = self._create_database(schema_version=None)

        with self.assertRaises(MissingSchemaVersionError):
            with open_oscar_database(self.database_path):
                self.fail("database without a schema version must not be exposed")

        self.assertEqual(self.database_path.read_bytes(), original_database)


if __name__ == "__main__":
    unittest.main()
