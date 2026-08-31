"""Deterministic tests for one-session OSCAR summary extraction."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pap_pilot.adapter import (
    InvalidSessionSummaryError,
    OscarMachineProvenance,
    OscarProfileProvenance,
    OscarSchemaProvenance,
    OscarSessionBoundaries,
    OscarSessionSettings,
    OscarSessionSummary,
    OscarSettingSource,
    SessionNotFoundError,
    extract_session_summary,
)


class SessionSummaryTests(unittest.TestCase):
    """Use only a minimal synthetic schema-17 database fixture."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "oscar.db"
        self._create_database()

    def _create_database(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE schema_version (
                    version INTEGER NOT NULL,
                    applied_at TEXT
                );
                CREATE TABLE profiles (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE user_info (
                    profile_id INTEGER NOT NULL,
                    timezone TEXT
                );
                CREATE TABLE profile_preferences (
                    profile_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    data_type TEXT NOT NULL
                );
                CREATE TABLE machines (
                    id INTEGER PRIMARY KEY,
                    profile_id INTEGER NOT NULL,
                    machine_id INTEGER NOT NULL,
                    loader_name TEXT NOT NULL,
                    machine_type INTEGER NOT NULL,
                    brand TEXT,
                    model TEXT,
                    series TEXT,
                    model_number TEXT,
                    serial_number TEXT,
                    data_version INTEGER NOT NULL,
                    last_imported TEXT,
                    purge_date TEXT
                );
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER NOT NULL,
                    machine_id INTEGER NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    duration INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    summary_only INTEGER NOT NULL,
                    no_settings INTEGER NOT NULL,
                    events_loaded INTEGER NOT NULL
                );
                CREATE TABLE channels (
                    profile_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    channel_code TEXT NOT NULL
                );
                CREATE TABLE session_settings (
                    session_id INTEGER NOT NULL,
                    profile_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    value REAL,
                    data_type TEXT NOT NULL,
                    json_value TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO schema_version VALUES (?, ?)",
                (17, "2026-08-01 00:00:00"),
            )
            connection.execute(
                "INSERT INTO profiles VALUES (?, ?, ?)",
                (1, "fixture-profile", "active"),
            )
            connection.execute(
                "INSERT INTO user_info VALUES (?, ?)",
                (1, "America/Denver"),
            )
            connection.executemany(
                "INSERT INTO profile_preferences VALUES (?, ?, ?, ?, ?)",
                (
                    (1, "profile", "TimeZone", "America/Denver", "string"),
                    (1, "profile", "DaySplitTime", "12:00:00", "time"),
                    (1, "profile", "LockSummarySessions", "false", "bool"),
                ),
            )
            connection.execute(
                """
                INSERT INTO machines VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    10,
                    1,
                    42,
                    "ResMedLoader",
                    1,
                    "ResMed",
                    "AirCurve 10 ASV",
                    "AirCurve 10",
                    "fixture-model",
                    "fixture-serial",
                    9,
                    "2026-08-30T12:00:00Z",
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    100,
                    7001,
                    10,
                    1_800_000_000_000,
                    1_800_028_800_000,
                    28_800_000,
                    1,
                    0,
                    0,
                    0,
                ),
            )
            setting_rows = (
                (101, "PAPMode", 6.0),
                (102, "RMS9_Mode", 7.0),
                (103, "EPAP", 5.0),
                (104, "PSMin", 1.0),
                (105, "PSMax", 10.0),
                (106, "IPAPHi", 15.0),
            )
            connection.executemany(
                "INSERT INTO channels VALUES (?, ?, ?)",
                ((1, channel_id, code) for channel_id, code, _ in setting_rows),
            )
            connection.executemany(
                "INSERT INTO session_settings VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (100, 1, channel_id, value, "numeric", None)
                    for channel_id, _, value in setting_rows
                ),
            )
            connection.commit()

    def _update(self, statement: str, parameters: tuple[object, ...]) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(statement, parameters)
            connection.commit()

    def test_extracts_deterministic_session_summary_with_provenance(self) -> None:
        original_database = self.database_path.read_bytes()

        summary = extract_session_summary(self.database_path, 100)

        self.assertEqual(
            summary,
            OscarSessionSummary(
                schema=OscarSchemaProvenance(
                    version=17,
                    applied_at="2026-08-01 00:00:00",
                ),
                profile=OscarProfileProvenance(
                    database_id=1,
                    name="fixture-profile",
                    status="active",
                    timezone="America/Denver",
                    day_split_time="12:00:00",
                    lock_summary_sessions_raw="false",
                ),
                machine=OscarMachineProvenance(
                    database_id=10,
                    source_id=42,
                    loader_name="ResMedLoader",
                    machine_type_code=1,
                    brand="ResMed",
                    model="AirCurve 10 ASV",
                    series="AirCurve 10",
                    model_number="fixture-model",
                    serial_number="fixture-serial",
                    loader_data_version=9,
                    last_imported_at="2026-08-30T12:00:00Z",
                    purge_cutoff_date=None,
                ),
                session=OscarSessionBoundaries(
                    database_id=100,
                    source_id=7001,
                    machine_database_id=10,
                    raw_start_ms=1_800_000_000_000,
                    raw_end_ms=1_800_028_800_000,
                    raw_duration_ms=28_800_000,
                    enabled=True,
                    summary_only=False,
                    no_settings=False,
                    events_loaded=False,
                ),
                settings=OscarSessionSettings(
                    therapy_mode_code=6,
                    loader_mode_code=7,
                    epap_cm_h2o=5.0,
                    ps_min_cm_h2o=1.0,
                    ps_max_cm_h2o=10.0,
                    max_ipap_cm_h2o=15.0,
                    sources=(
                        OscarSettingSource("PAPMode", 101),
                        OscarSettingSource("RMS9_Mode", 102),
                        OscarSettingSource("EPAP", 103),
                        OscarSettingSource("PSMin", 104),
                        OscarSettingSource("PSMax", 105),
                        OscarSettingSource("IPAPHi", 106),
                    ),
                ),
            ),
        )
        self.assertEqual(self.database_path.read_bytes(), original_database)

    def test_missing_session_fails_safely(self) -> None:
        with self.assertRaises(SessionNotFoundError):
            extract_session_summary(self.database_path, 999)

    def test_missing_required_setting_fails_safely(self) -> None:
        self._update(
            "DELETE FROM session_settings WHERE channel_id = ?",
            (104,),
        )
        database_before_extraction = self.database_path.read_bytes()

        with self.assertRaises(InvalidSessionSummaryError):
            extract_session_summary(self.database_path, 100)

        self.assertEqual(
            self.database_path.read_bytes(),
            database_before_extraction,
        )

    def test_invalid_session_boundaries_fail_safely(self) -> None:
        self._update(
            "UPDATE sessions SET duration = ? WHERE id = ?",
            (0, 100),
        )

        with self.assertRaises(InvalidSessionSummaryError):
            extract_session_summary(self.database_path, 100)

    def test_conflicting_profile_timezone_fails_safely(self) -> None:
        self._update(
            "UPDATE user_info SET timezone = ? WHERE profile_id = ?",
            ("America/New_York", 1),
        )

        with self.assertRaises(InvalidSessionSummaryError):
            extract_session_summary(self.database_path, 100)


if __name__ == "__main__":
    unittest.main()
