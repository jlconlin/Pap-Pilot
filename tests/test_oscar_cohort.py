"""Focused tests for explicit retrospective OSCAR cohort extraction."""

from contextlib import closing
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from pap_pilot.adapter import (
    OscarCohortError,
    OscarCohortSelection,
    OscarCorrectionEvidenceState,
    OscarCorrectionType,
    SessionNotFoundError,
    extract_normalized_oscar_cohort,
)
from pap_pilot.adapter.oscar import open_oscar_database

from tests import test_session_summary


_SECOND_SESSION_START_MS = 1_800_030_600_000
_SECOND_SESSION_END_MS = 1_800_034_200_000
_NEXT_NIGHT_START_MS = 1_800_086_400_000
_NEXT_NIGHT_END_MS = 1_800_115_200_000


class OscarCohortTests(unittest.TestCase):
    """Exercise only disposable synthetic schema-17 databases."""

    def setUp(self) -> None:
        fixture = test_session_summary.SessionSummaryTests(methodName="test_extracts_deterministic_session_summary_with_provenance")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.database_path = fixture.database_path
        self._extend_to_multi_night_cohort()

    def _execute(self, statement: str, parameters: tuple[object, ...] = ()) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(statement, parameters)
            connection.commit()

    def _extend_to_multi_night_cohort(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE device_time_corrections (
                    id INTEGER PRIMARY KEY,
                    machine_id INTEGER NOT NULL,
                    date_from TEXT NOT NULL,
                    date_to TEXT,
                    type TEXT NOT NULL,
                    offset_ms INTEGER,
                    c0_ms INTEGER,
                    c1 REAL,
                    reason TEXT,
                    applied_at TEXT NOT NULL,
                    undone_at TEXT
                );
                """
            )
            connection.execute(
                """
                INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (101, 7002, 10, _SECOND_SESSION_START_MS, _SECOND_SESSION_END_MS, 3_600_000, 1, 0, 0, 0),
            )
            connection.execute(
                """
                INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (102, 7003, 10, _NEXT_NIGHT_START_MS, _NEXT_NIGHT_END_MS, 28_800_000, 1, 0, 0, 0),
            )
            connection.execute(
                "UPDATE session_settings SET value = 2.0 WHERE session_id = 100 AND channel_id = 104"
            )
            connection.execute(
                """
                INSERT INTO session_settings
                SELECT 101, profile_id, channel_id, value, data_type, json_value
                FROM session_settings
                WHERE session_id = 100
                """
            )
            connection.execute(
                """
                INSERT INTO session_settings
                SELECT 102, profile_id, channel_id, value, data_type, json_value
                FROM session_settings
                WHERE session_id = 100
                """
            )
            connection.execute(
                "UPDATE session_settings SET value = 1.0 WHERE session_id = 102 AND channel_id = 104"
            )
            connection.executemany(
                "INSERT INTO device_time_corrections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (1, 10, "2027-01-14", "2027-01-14", "timezone", 60_000, None, None, "synthetic timezone correction", "2027-02-01T00:00:00Z", None),
                    (2, 10, "2027-01-15", None, "travel", -120_000, None, None, "synthetic travel correction", "2027-02-02T00:00:00Z", None),
                    (3, 10, "2027-01-15", "2099-12-31", "reset", 999_000, None, None, "undone synthetic reset", "2027-02-03T00:00:00Z", "2027-02-04T00:00:00Z"),
                    (4, 10, "2027-01-14", "2027-01-14", "offset", 5_000, None, None, "stacked synthetic offset", "2027-02-01T00:01:00Z", None),
                ),
            )
            connection.commit()

    def test_extracts_explicit_reproducible_multi_night_cohort_without_writing_source(self) -> None:
        original_bytes = self.database_path.read_bytes()
        self.database_path.chmod(0o400)
        selection = OscarCohortSelection((102, 100, 101))

        first = extract_normalized_oscar_cohort(self.database_path, selection, trusted_immutable_copy=True)
        second = extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((101, 102, 100)), trusted_immutable_copy=True)

        self.assertEqual(first, second)
        self.assertEqual(first.record_id, second.record_id)
        self.assertEqual(first.selection.session_database_ids, (100, 101, 102))
        self.assertEqual(first.profile_database_id, 1)
        self.assertEqual(first.machine_database_id, 10)
        self.assertEqual(first.schema_version, 17)
        self.assertEqual([night.local_date for night in first.nights], ["2027-01-14", "2027-01-15"])
        self.assertEqual([len(night.sessions) for night in first.nights], [2, 1])

        sessions = tuple(session for night in first.nights for session in night.sessions)
        self.assertEqual([session.start_time_ms for session in sessions], [1_800_000_000_000, _SECOND_SESSION_START_MS, _NEXT_NIGHT_START_MS])
        self.assertEqual([self._setting(session, "ps_min") for session in sessions], [2.0, 2.0, 1.0])
        self.assertTrue(all(session.signals for session in sessions))
        self.assertTrue(all(signal.segments for signal in sessions[0].signals))
        self.assertTrue(all(not signal.segments for session in sessions[1:] for signal in session.signals))
        self.assertEqual(
            {self._source_value(signal.provenance, "signal.availability") for signal in sessions[1].signals},
            {"data_missing"},
        )
        self.assertEqual(
            {reference.source_record_id for reference in first.nights[0].provenance.source_references if reference.source_record_type == "sessions.id"},
            {"100", "101"},
        )
        self.assertEqual(
            self._source_value(first.nights[0].provenance, "night.selected_session_count"),
            2,
        )

        evidence = {value.session_database_id: value for value in first.session_time_evidence}
        self.assertEqual(evidence[100].state, OscarCorrectionEvidenceState.SUPPORTED_CONSTANT)
        self.assertEqual(evidence[100].total_offset_ms, 65_000)
        self.assertEqual(evidence[100].corrected_start_ms, evidence[100].raw_start_ms + 65_000)
        self.assertEqual(evidence[101].total_offset_ms, 65_000)
        self.assertEqual(evidence[102].total_offset_ms, -120_000)
        self.assertEqual(evidence[102].corrected_end_ms, evidence[102].raw_end_ms - 120_000)
        self.assertEqual([row.source_correction_id for row in evidence[102].observed_corrections], [2, 3])
        self.assertFalse(evidence[102].observed_corrections[1].is_active)
        self.assertEqual(evidence[102].observed_corrections[1].correction_type, OscarCorrectionType.RESET)
        self.assertEqual(sessions[2].start_time_ms, evidence[102].raw_start_ms)
        self.assertIn("device_time_corrections.id:3", evidence[102].source_record_ids)
        self.assertIn("channels.channel_id:104", first.source_record_ids)
        self.assertIn("respiratory_events.id:1", first.source_record_ids)
        self.assertIn("event_lists.id:401", first.source_record_ids)
        self.assertIn("event_data.id:501", first.source_record_ids)
        self.assertEqual(self.database_path.read_bytes(), original_bytes)

    def test_selection_is_explicit_nonempty_unique_and_canonical(self) -> None:
        self.assertEqual(OscarCohortSelection((2, 1)).session_database_ids, (1, 2))
        for invalid in ((), (1, 1), (0,), (-1,), (True,)):
            with self.subTest(invalid=invalid), self.assertRaises(OscarCohortError):
                OscarCohortSelection(invalid)
        with self.assertRaises(OscarCohortError):
            OscarCohortSelection([1])  # type: ignore[arg-type]

    def test_missing_selected_session_fails_without_modifying_database(self) -> None:
        original_bytes = self.database_path.read_bytes()

        with self.assertRaisesRegex(SessionNotFoundError, "selected OSCAR session"):
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100, 999)))

        self.assertEqual(self.database_path.read_bytes(), original_bytes)

    def test_rejects_selection_across_machines_before_signal_extraction(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO machines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (11, 1, 43, "ResMedLoader", 1, "ResMed", "Other", "Other", "other-model", "other-serial", 9, None, None),
            )
            connection.execute("UPDATE sessions SET machine_id = 11 WHERE id = 101")
            connection.commit()

        with self.assertRaisesRegex(OscarCohortError, "one supported OSCAR schema, profile, and machine"):
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100, 101)))

    def test_reports_confirmed_absence_after_querying_correction_table(self) -> None:
        self._execute("DELETE FROM device_time_corrections")

        cohort = extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100,)))

        evidence = cohort.session_time_evidence[0]
        self.assertEqual(evidence.state, OscarCorrectionEvidenceState.CONFIRMED_NONE)
        self.assertEqual(evidence.total_offset_ms, 0)
        self.assertEqual(evidence.corrected_start_ms, evidence.raw_start_ms)
        self.assertEqual(evidence.corrected_end_ms, evidence.raw_end_ms)
        self.assertIn("device_time_corrections.machine_id:10:queried", evidence.source_record_ids)

    def test_retains_unsupported_drift_without_deriving_corrected_bounds(self) -> None:
        self._execute("DELETE FROM device_time_corrections")
        self._execute(
            "INSERT INTO device_time_corrections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (9, 10, "2027-01-14", None, "drift", None, 25, 0.5, "synthetic drift", "2027-03-01T00:00:00Z", None),
        )

        cohort = extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100,)))

        evidence = cohort.session_time_evidence[0]
        self.assertEqual(evidence.state, OscarCorrectionEvidenceState.UNSUPPORTED_DRIFT)
        self.assertIsNone(evidence.total_offset_ms)
        self.assertIsNone(evidence.corrected_start_ms)
        self.assertIsNone(evidence.corrected_end_ms)
        self.assertEqual(evidence.raw_start_ms, cohort.nights[0].sessions[0].start_time_ms)

    def test_rejects_unavailable_or_malformed_correction_evidence(self) -> None:
        self._execute("DROP TABLE device_time_corrections")
        with self.assertRaisesRegex(OscarCohortError, "correction evidence is unavailable"):
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100,)))

        self._execute(
            """
            CREATE TABLE device_time_corrections (
                id INTEGER PRIMARY KEY, machine_id INTEGER NOT NULL, date_from TEXT NOT NULL, date_to TEXT,
                type TEXT NOT NULL, offset_ms INTEGER, c0_ms INTEGER, c1 REAL, reason TEXT, applied_at TEXT NOT NULL, undone_at TEXT
            )
            """
        )
        self._execute(
            "INSERT INTO device_time_corrections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (7, 10, "2027-01-14", None, "unknown", 10, None, None, None, "2027-03-01T00:00:00Z", None),
        )
        with self.assertRaisesRegex(OscarCohortError, "unsupported type"):
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100,)))

        self._execute("DELETE FROM device_time_corrections")
        self._execute(
            "INSERT INTO device_time_corrections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (8, 10, "2027-01-14", None, "timezone", None, None, None, None, "2027-03-01T00:00:00Z", None),
        )
        with self.assertRaisesRegex(OscarCohortError, "constant correction"):
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100,)))

        self._execute("DELETE FROM device_time_corrections")
        self._execute(
            "INSERT INTO device_time_corrections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (9, 10, "2027-01-15", "2027-01-14", "offset", 10, None, None, None, "2027-03-01T00:00:00Z", None),
        )
        with self.assertRaisesRegex(OscarCohortError, "cannot be reversed"):
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100,)))

    def test_uses_one_guarded_database_transaction(self) -> None:
        with patch("pap_pilot.adapter.cohort.open_oscar_database", wraps=open_oscar_database) as guarded_open:
            extract_normalized_oscar_cohort(self.database_path, OscarCohortSelection((100, 101, 102)))

        self.assertEqual(guarded_open.call_count, 1)

    def test_contract_records_are_frozen(self) -> None:
        selection = OscarCohortSelection((100,))
        cohort = extract_normalized_oscar_cohort(self.database_path, selection)

        with self.assertRaises(FrozenInstanceError):
            selection.record_version = 2  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            cohort.machine_database_id = 11  # type: ignore[misc]

    @staticmethod
    def _setting(session: object, name: str) -> object:
        return next(value.value for value in session.settings if value.name == name)

    @staticmethod
    def _source_value(provenance: object, name: str) -> object:
        return json.loads(next(value.value for value in provenance.source_values if value.name == name))


if __name__ == "__main__":
    unittest.main()
