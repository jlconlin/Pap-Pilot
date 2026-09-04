"""Focused tests for structured, append-only sleep-journal evidence."""

from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pap_pilot.engine import (
    ConfounderKind,
    ConfounderReportStatus,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentRecord,
    ExperimentStore,
    ExperimentStoreError,
    LOCAL_EXPERIMENT_DATABASE_FILENAME,
    SLEEP_JOURNAL_SCHEMA_ID,
    SLEEP_JOURNAL_SCHEMA_VERSION,
    SleepJournalConfounder,
    SleepJournalEntry,
    SleepJournalEntryRecordedPayload,
    SleepJournalModelError,
    SourceClass,
)


class SleepJournalTests(unittest.TestCase):
    """Verify journal semantics, exact text, atomic append, and correction replay."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / LOCAL_EXPERIMENT_DATABASE_FILENAME
        self.experiment = ExperimentRecord("experiment:one", "Journal experiment", 1_000, "user:local", ("provenance:user",))

    def test_structured_entry_has_explicit_scales_and_preserves_original_text(self) -> None:
        note = "  Woke before the alarm.\nFelt better after breakfast.  "
        details = "  Two time zones east  "
        entry = self._entry("journal:one", note=note, confounders=(SleepJournalConfounder(ConfounderKind.TRAVEL, details),))

        self.assertEqual((entry.awakenings_count, entry.sleep_quality, entry.morning_energy, entry.daytime_tiredness), (2, 4, 4, 2))
        self.assertEqual(entry.original_note, note)
        self.assertEqual(entry.confounders[0].details, details)
        self.assertEqual((entry.schema_id, entry.schema_version), (SLEEP_JOURNAL_SCHEMA_ID, SLEEP_JOURNAL_SCHEMA_VERSION))
        with self.assertRaises(FrozenInstanceError):
            entry.sleep_quality = 5  # type: ignore[misc]

    def test_missing_answers_invalid_scales_and_confounder_states_fail(self) -> None:
        with self.assertRaisesRegex(SleepJournalModelError, "1 through 5"):
            replace(self._entry("journal:one"), sleep_quality=6)
        with self.assertRaisesRegex(SleepJournalModelError, "nonnegative"):
            replace(self._entry("journal:one"), awakenings_count=-1)
        with self.assertRaisesRegex(SleepJournalModelError, "Reported confounders"):
            replace(self._entry("journal:one"), confounder_status=ConfounderReportStatus.NONE_REPORTED)
        with self.assertRaisesRegex(SleepJournalModelError, "at least one"):
            SleepJournalEntry(
                "journal:empty",
                "night:one",
                2_000,
                "user:local",
                None,
                None,
                None,
                None,
                ConfounderReportStatus.NOT_REPORTED,
                (),
                None,
                ("provenance:user",),
            )
        with self.assertRaisesRegex(SleepJournalModelError, "other confounder"):
            SleepJournalConfounder(ConfounderKind.OTHER)

    def test_append_reopen_and_correction_replay_retain_both_original_entries(self) -> None:
        original = self._entry("journal:original", note="Original note")
        correction = self._entry("journal:correction", note="Corrected note")
        original_event = self._event(original, 1, "event:journal-original")
        correction_event = self._event(correction, 2, "event:journal-correction", correction_of=original_event.record_id)

        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_journal_entry(original_event, original)
            store.append_journal_entry(correction_event, correction)
            replayed = store.replay(self.experiment.record_id)

        self.assertEqual(replayed.journal_history, (original, correction))
        self.assertEqual(replayed.effective_journal_entries, (correction,))
        self.assertEqual(replayed.history, (original_event, correction_event))
        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.replay(self.experiment.record_id), replayed)

    def test_journal_and_event_append_is_atomic_and_rejects_dangling_references(self) -> None:
        entry = self._entry("journal:one")
        event = self._event(entry, 1, "event:journal")

        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            with self.assertRaisesRegex(ExperimentStoreError, "atomically"):
                store.append_event(event)
            with self.assertRaisesRegex(ExperimentStoreError, "exact journal entry"):
                store.append_journal_entry(event, replace(entry, record_id="journal:other"))
            self.assertEqual(store.read_history(self.experiment.record_id), ())
            store.append_journal_entry(event, entry)
            with self.assertRaises(ExperimentStoreError):
                store.append_journal_entry(self._event(entry, 2, "event:duplicate-entry"), entry)
            self.assertEqual(store.read_history(self.experiment.record_id), (event,))

    def test_sqlite_rejects_journal_update_delete_and_replacement(self) -> None:
        entry = self._entry("journal:one")
        event = self._event(entry, 1, "event:journal")
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_journal_entry(event, entry)

        with closing(sqlite3.connect(self.database_path)) as inspection:
            row = inspection.execute("SELECT record_id, night_record_id, reported_at_ms, reported_by, record_json FROM sleep_journal_entries").fetchone()
        statements = (
            ("UPDATE sleep_journal_entries SET record_json = '{}' WHERE record_id = ?", (entry.record_id,)),
            ("DELETE FROM sleep_journal_entries WHERE record_id = ?", (entry.record_id,)),
            ("INSERT OR REPLACE INTO sleep_journal_entries (record_id, night_record_id, reported_at_ms, reported_by, record_json) VALUES (?, ?, ?, ?, ?)", row),
        )
        for statement, parameters in statements:
            with self.subTest(statement=statement.split()[0]), closing(sqlite3.connect(self.database_path)) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement, parameters)
        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.replay(self.experiment.record_id).journal_history, (entry,))

    def test_version_one_store_is_migrated_without_changing_existing_history(self) -> None:
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DROP TRIGGER retrospective_night_evidence_no_update")
            connection.execute("DROP TRIGGER retrospective_night_evidence_no_delete")
            connection.execute("DROP TRIGGER retrospective_night_evidence_no_replace")
            connection.execute("DROP TRIGGER sleep_journal_entries_no_update")
            connection.execute("DROP TRIGGER sleep_journal_entries_no_delete")
            connection.execute("DROP TRIGGER sleep_journal_entries_no_replace")
            connection.execute("DROP TABLE retrospective_night_evidence")
            connection.execute("DROP TABLE sleep_journal_entries")
            connection.execute("UPDATE pap_pilot_metadata SET value = '1' WHERE key = 'schema_version'")
            connection.commit()

        with ExperimentStore(self.database_path) as migrated:
            self.assertEqual(migrated.get_experiment(self.experiment.record_id), self.experiment)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM pap_pilot_metadata WHERE key = 'schema_version'").fetchone()[0], "3")
            self.assertIn("sleep_journal_entries", {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")})
            self.assertIn("retrospective_night_evidence", {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")})

    def _entry(self, record_id: str, *, note: str | None = "Slept reasonably well.", confounders: tuple[SleepJournalConfounder, ...] = (SleepJournalConfounder(ConfounderKind.STRESS, "Work deadline"),)) -> SleepJournalEntry:
        return SleepJournalEntry(
            record_id=record_id,
            night_record_id="night:one",
            reported_at_ms=2_000,
            reported_by="user:local",
            awakenings_count=2,
            sleep_quality=4,
            morning_energy=4,
            daytime_tiredness=2,
            confounder_status=ConfounderReportStatus.REPORTED,
            confounders=confounders,
            original_note=note,
            source_provenance_ids=("provenance:user",),
        )

    def _event(self, entry: SleepJournalEntry, sequence: int, record_id: str, *, correction_of: str | None = None) -> ExperimentEvent:
        return ExperimentEvent(
            record_id=record_id,
            experiment_record_id=self.experiment.record_id,
            sequence_number=sequence,
            event_type=ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED,
            recorded_at_ms=entry.reported_at_ms,
            recorded_by=entry.reported_by,
            payload=SleepJournalEntryRecordedPayload(entry.record_id, entry.night_record_id),
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=(self.experiment.record_id, entry.night_record_id),
            source_provenance_ids=entry.source_provenance_ids,
            correction_of_event_id=correction_of,
        )


if __name__ == "__main__":
    unittest.main()
