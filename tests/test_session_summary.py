"""Deterministic tests for one-session OSCAR summary extraction."""

from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
import zlib

from pap_pilot.adapter import (
    FLOW_RATE_CANONICAL_UNIT,
    FLOW_RATE_CHANNEL_CODE,
    FLOW_RATE_SAMPLE_INTERVAL_MS,
    FLOW_RATE_SOURCE_DIMENSION,
    InvalidFlowSignalError,
    InvalidSessionEventError,
    InvalidSessionSummaryError,
    OscarEventCompleteness,
    OscarEventKind,
    OscarEventSourceClass,
    OscarFlowAvailability,
    OscarSignalSourceClass,
    OscarSignalStorage,
    OscarMachineProvenance,
    OscarProfileProvenance,
    OscarSchemaProvenance,
    OscarSessionBoundaries,
    OscarSessionEvent,
    OscarSessionSettings,
    OscarSessionSummary,
    OscarSettingSource,
    OscarObservedEventCount,
    SessionNotFoundError,
    extract_flow_rate_signal,
    extract_session_events,
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
                CREATE TABLE respiratory_events (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER NOT NULL,
                    profile_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    event_type INTEGER NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    duration INTEGER NOT NULL
                );
                CREATE TABLE event_lists (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER NOT NULL,
                    profile_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    eventlist_index INTEGER NOT NULL DEFAULT 0,
                    event_type INTEGER NOT NULL,
                    first_time INTEGER NOT NULL,
                    last_time INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    rate REAL NOT NULL DEFAULT 0,
                    gain REAL NOT NULL DEFAULT 1.0,
                    offset REAL NOT NULL DEFAULT 0.0,
                    min_value REAL NOT NULL DEFAULT 0.0,
                    max_value REAL NOT NULL DEFAULT 0.0,
                    dimension TEXT,
                    has_second_field INTEGER NOT NULL DEFAULT 0,
                    min2_value REAL,
                    max2_value REAL,
                    data_size INTEGER NOT NULL DEFAULT 0,
                    compressed_size INTEGER
                );
                CREATE TABLE event_data (
                    id INTEGER PRIMARY KEY,
                    eventlist_id INTEGER NOT NULL UNIQUE,
                    data_blob BLOB,
                    data_compressed BLOB,
                    data2_blob BLOB,
                    data2_compressed BLOB,
                    time_blob BLOB,
                    time_compressed BLOB,
                    compression_method INTEGER NOT NULL DEFAULT 0,
                    checksum INTEGER
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
            event_channel_rows = (
                (201, "Obstructive"),
                (202, "ClearAirway"),
                (203, "Apnea"),
                (204, "Hypopnea"),
                (205, "RERA"),
                (206, "LeakSpan"),
                (207, "AllApnea"),
            )
            connection.executemany(
                "INSERT INTO channels VALUES (?, ?, ?)",
                ((1, channel_id, code) for channel_id, code in event_channel_rows),
            )
            connection.executemany(
                "INSERT INTO respiratory_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (1, 100, 1, 201, 42, 1_800_000_060_000, 1_800_000_070_000, 10),
                    (2, 100, 1, 202, 42, 1_800_000_120_000, 1_800_000_130_000, 10),
                    (3, 100, 1, 203, 1, 1_800_000_180_000, 1_800_000_190_000, 10),
                    (4, 100, 1, 204, 1, 1_800_000_240_000, 1_800_000_250_000, 10),
                    (5, 100, 1, 205, 42, 1_800_000_300_000, 1_800_000_310_000, 10),
                    (6, 100, 1, 206, 0, 1_800_028_795_000, 1_800_028_805_000, 10),
                    (7, 100, 1, 207, 42, 1_800_000_360_000, 1_800_000_370_000, 10),
                    (8, 100, 1, 204, 1, 1_800_000_420_000, 1_800_000_430_000, 10),
                ),
            )
            connection.execute(
                "INSERT INTO channels VALUES (?, ?, ?)",
                (1, 301, FLOW_RATE_CHANNEL_CODE),
            )
            raw_flow_0 = struct.pack("<3h", -100, 0, 100)
            raw_flow_1 = struct.pack("<2h", 50, -50)
            compressed_flow_1 = (
                len(raw_flow_1).to_bytes(4, byteorder="big")
                + zlib.compress(raw_flow_1)
            )
            connection.executemany(
                """
                INSERT INTO event_lists VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    (
                        401,
                        100,
                        1,
                        301,
                        0,
                        0,
                        1_800_000_001_000,
                        1_800_000_001_120,
                        3,
                        40.0,
                        0.12,
                        0.5,
                        -11.5,
                        12.5,
                        "L/M",
                        0,
                        None,
                        None,
                        len(raw_flow_0),
                        len(raw_flow_0),
                    ),
                    (
                        402,
                        100,
                        1,
                        301,
                        1,
                        0,
                        1_800_000_002_000,
                        1_800_000_002_080,
                        2,
                        40.0,
                        0.12,
                        0.5,
                        -5.5,
                        6.5,
                        "L/M",
                        0,
                        None,
                        None,
                        len(raw_flow_1),
                        len(compressed_flow_1),
                    ),
                ),
            )
            connection.executemany(
                """
                INSERT INTO event_data VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    (
                        501,
                        401,
                        raw_flow_0,
                        None,
                        None,
                        None,
                        None,
                        None,
                        0,
                        30_214,
                    ),
                    (
                        502,
                        402,
                        None,
                        compressed_flow_1,
                        None,
                        None,
                        None,
                        None,
                        1,
                        54_936,
                    ),
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

    def test_extracts_allowlisted_events_with_raw_provenance(self) -> None:
        original_database = self.database_path.read_bytes()
        session_summary = extract_session_summary(self.database_path, 100)

        result = extract_session_events(self.database_path, 100)

        self.assertEqual(result.session_summary, session_summary)
        expected_event_data = (
            (1, 201, "Obstructive", OscarEventKind.OBSTRUCTIVE_APNEA, "OA", 42,
             1_800_000_060_000, 1_800_000_070_000, True),
            (2, 202, "ClearAirway", OscarEventKind.CLEAR_AIRWAY_APNEA, "CA", 42,
             1_800_000_120_000, 1_800_000_130_000, True),
            (3, 203, "Apnea", OscarEventKind.UNCLASSIFIED_APNEA, "UA", 1,
             1_800_000_180_000, 1_800_000_190_000, True),
            (4, 204, "Hypopnea", OscarEventKind.HYPOPNEA, "H", 1,
             1_800_000_240_000, 1_800_000_250_000, True),
            (5, 205, "RERA", OscarEventKind.RERA, "RE", 42,
             1_800_000_300_000, 1_800_000_310_000, True),
            (8, 204, "Hypopnea", OscarEventKind.HYPOPNEA, "H", 1,
             1_800_000_420_000, 1_800_000_430_000, True),
            (6, 206, "LeakSpan", OscarEventKind.LARGE_LEAK, "LL", 0,
             1_800_028_795_000, 1_800_028_805_000, False),
        )
        expected_events = tuple(
            OscarSessionEvent(
                source_event_id=event_id,
                session_database_id=100,
                profile_database_id=1,
                source_channel_id=channel_id,
                channel_code=channel_code,
                event_kind=event_kind,
                oscar_label=label,
                source_event_type=event_type,
                raw_start_ms=start_ms,
                raw_end_ms=end_ms,
                duration_s=10,
                contained_within_session=contained,
                source_class=(
                    OscarEventSourceClass.MACHINE_LABELED_OSCAR_NORMALIZED
                ),
            )
            for (
                event_id,
                channel_id,
                channel_code,
                event_kind,
                label,
                event_type,
                start_ms,
                end_ms,
                contained,
            ) in expected_event_data
        )
        self.assertEqual(result.events, expected_events)
        self.assertEqual(
            result.observed_row_counts,
            tuple(
                OscarObservedEventCount(
                    event_kind=event_kind,
                    oscar_label=label,
                    observed_rows=observed_rows,
                    completeness=OscarEventCompleteness.UNKNOWN,
                )
                for event_kind, label, observed_rows in (
                    (OscarEventKind.OBSTRUCTIVE_APNEA, "OA", 1),
                    (OscarEventKind.CLEAR_AIRWAY_APNEA, "CA", 1),
                    (OscarEventKind.UNCLASSIFIED_APNEA, "UA", 1),
                    (OscarEventKind.HYPOPNEA, "H", 2),
                    (OscarEventKind.RERA, "RE", 1),
                    (OscarEventKind.LARGE_LEAK, "LL", 1),
                )
            ),
        )
        self.assertEqual(result.completeness, OscarEventCompleteness.UNKNOWN)
        self.assertNotIn("AllApnea", {event.channel_code for event in result.events})
        self.assertEqual(self.database_path.read_bytes(), original_database)

    def test_empty_event_rows_preserve_unknown_completeness(self) -> None:
        self._update("DELETE FROM respiratory_events", ())

        result = extract_session_events(self.database_path, 100)

        self.assertEqual(result.events, ())
        self.assertEqual(result.completeness, OscarEventCompleteness.UNKNOWN)
        self.assertEqual(
            [count.observed_rows for count in result.observed_row_counts],
            [0, 0, 0, 0, 0, 0],
        )
        self.assertTrue(
            all(
                count.completeness is OscarEventCompleteness.UNKNOWN
                for count in result.observed_row_counts
            )
        )

    def test_event_duration_mismatch_fails_safely(self) -> None:
        self._update(
            "UPDATE respiratory_events SET duration = ? WHERE id = ?",
            (9, 3),
        )

        with self.assertRaises(InvalidSessionEventError):
            extract_session_events(self.database_path, 100)

    def test_event_profile_mismatch_fails_safely(self) -> None:
        self._update(
            "UPDATE respiratory_events SET profile_id = ? WHERE id = ?",
            (2, 4),
        )

        with self.assertRaises(InvalidSessionEventError):
            extract_session_events(self.database_path, 100)

    def test_extracts_stable_flow_segments_with_timestamps_and_units(self) -> None:
        original_database = self.database_path.read_bytes()

        result = extract_flow_rate_signal(self.database_path, 100)
        repeated_result = extract_flow_rate_signal(self.database_path, 100)

        self.assertEqual(result, repeated_result)
        self.assertEqual(result.availability, OscarFlowAvailability.AVAILABLE)
        self.assertEqual(result.source_channel_id, 301)
        self.assertEqual(result.channel_code, FLOW_RATE_CHANNEL_CODE)
        self.assertEqual(result.canonical_unit, FLOW_RATE_CANONICAL_UNIT)
        self.assertEqual(result.total_sample_count, 5)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(
            result.source_class,
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED,
        )

        first, second = result.segments
        self.assertEqual(first.source_eventlist_id, 401)
        self.assertEqual(first.source_event_data_id, 501)
        self.assertEqual(first.eventlist_index, 0)
        self.assertEqual(first.sample_count, 3)
        self.assertEqual(first.sample_interval_ms, FLOW_RATE_SAMPLE_INTERVAL_MS)
        self.assertEqual(
            first.raw_sample_times_ms,
            (
                1_800_000_001_000.0,
                1_800_000_001_040.0,
                1_800_000_001_080.0,
            ),
        )
        self.assertEqual(first.raw_last_sample_time_ms, 1_800_000_001_080.0)
        self.assertEqual(first.raw_end_time_ms_exclusive, 1_800_000_001_120)
        self.assertEqual(first.values_l_min, (-11.5, 0.5, 12.5))
        self.assertEqual(first.source_dimension, FLOW_RATE_SOURCE_DIMENSION)
        self.assertEqual(first.canonical_unit, FLOW_RATE_CANONICAL_UNIT)
        self.assertIsNone(first.gap_before_ms)
        self.assertEqual(first.storage, OscarSignalStorage.UNCOMPRESSED)
        self.assertEqual(first.data_size_bytes, 6)
        self.assertEqual(first.compressed_size_bytes, 6)
        self.assertEqual(first.source_checksum, 30_214)

        self.assertEqual(second.source_eventlist_id, 402)
        self.assertEqual(second.source_event_data_id, 502)
        self.assertEqual(second.eventlist_index, 1)
        self.assertEqual(second.sample_count, 2)
        self.assertEqual(
            second.raw_sample_times_ms,
            (1_800_000_002_000.0, 1_800_000_002_040.0),
        )
        self.assertEqual(second.raw_end_time_ms_exclusive, 1_800_000_002_080)
        self.assertEqual(second.values_l_min, (6.5, -5.5))
        self.assertEqual(second.gap_before_ms, 880)
        self.assertEqual(second.storage, OscarSignalStorage.QT_ZLIB)
        self.assertEqual(second.data_size_bytes, 4)
        self.assertEqual(second.source_checksum, 54_936)
        self.assertEqual(self.database_path.read_bytes(), original_database)

    def test_missing_flow_eventlists_are_explicit(self) -> None:
        self._update("DELETE FROM event_lists", ())

        result = extract_flow_rate_signal(self.database_path, 100)

        self.assertEqual(result.availability, OscarFlowAvailability.DATA_MISSING)
        self.assertEqual(result.source_channel_id, 301)
        self.assertEqual(result.segments, ())
        self.assertEqual(result.total_sample_count, 0)

    def test_missing_flow_channel_is_explicit(self) -> None:
        self._update(
            "DELETE FROM channels WHERE channel_code = ?",
            (FLOW_RATE_CHANNEL_CODE,),
        )

        result = extract_flow_rate_signal(self.database_path, 100)

        self.assertEqual(
            result.availability,
            OscarFlowAvailability.CHANNEL_MISSING,
        )
        self.assertIsNone(result.source_channel_id)
        self.assertEqual(result.segments, ())

    def test_flow_checksum_mismatch_fails_safely(self) -> None:
        self._update(
            "UPDATE event_data SET checksum = ? WHERE id = ?",
            (0, 501),
        )

        with self.assertRaises(InvalidFlowSignalError):
            extract_flow_rate_signal(self.database_path, 100)

    def test_noncontiguous_flow_eventlists_fail_safely(self) -> None:
        self._update(
            "UPDATE event_lists SET eventlist_index = ? WHERE id = ?",
            (2, 402),
        )

        with self.assertRaises(InvalidFlowSignalError):
            extract_flow_rate_signal(self.database_path, 100)

    def test_flow_profile_mismatch_fails_safely(self) -> None:
        self._update(
            "UPDATE event_lists SET profile_id = ? WHERE id = ?",
            (2, 401),
        )

        with self.assertRaises(InvalidFlowSignalError):
            extract_flow_rate_signal(self.database_path, 100)

    def test_missing_flow_data_row_fails_safely(self) -> None:
        self._update("DELETE FROM event_data WHERE id = ?", (502,))

        with self.assertRaises(InvalidFlowSignalError):
            extract_flow_rate_signal(self.database_path, 100)


if __name__ == "__main__":
    unittest.main()
