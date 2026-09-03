"""Focused tests for the local append-only experiment store."""

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pap_pilot.engine import (
    EXPERIMENT_STORE_RECORD_FORMAT,
    EXPERIMENT_STORE_RECORD_FORMAT_VERSION,
    EXPERIMENT_STORE_SCHEMA_ID,
    EXPERIMENT_STORE_SCHEMA_VERSION,
    LOCAL_EXPERIMENT_DATABASE_FILENAME,
    ConfounderReportStatus,
    EvaluationIssuedPayload,
    EvaluationSupersededPayload,
    ExperimentActionPayload,
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentModelError,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentRecord,
    ExperimentRevisedPayload,
    ExperimentSetting,
    ExperimentSettingChange,
    ExperimentStore,
    ExperimentStoreError,
    HypothesisDraftedPayload,
    NoteRecordedPayload,
    ObservationRecordedPayload,
    ProblemRecordedPayload,
    SettingChangeConfirmedPayload,
    SleepJournalEntryRecordedPayload,
    SleepJournalEntry,
    SourceClass,
    validate_experiment_history,
)


class ExperimentStoreTests(unittest.TestCase):
    """Verify durable replay and protections against destructive history changes."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / LOCAL_EXPERIMENT_DATABASE_FILENAME
        self.experiment = ExperimentRecord(
            record_id="experiment:ps-min-2-to-1",
            title="Retrospective PS Min 2 to 1",
            created_at_ms=1_788_300_000_000,
            created_by="user:local",
            source_provenance_ids=("provenance:user",),
        )
        self.baseline_settings = (
            ExperimentSetting("therapy_mode_code", 6),
            ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"),
            ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_max", 5.0, "cm H₂O"),
            ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        self.change = ExperimentSettingChange(
            ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_min", 1.0, "cm H₂O"),
        )

    def test_store_creates_only_the_approved_local_database_and_roundtrips_identity(self) -> None:
        self.assertFalse(self.database_path.exists())

        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            self.assertEqual(store.get_experiment(self.experiment.record_id), self.experiment)

        self.assertTrue(self.database_path.is_file())
        self.assertEqual(tuple(path.name for path in self.database_path.parent.iterdir()), (LOCAL_EXPERIMENT_DATABASE_FILENAME,))
        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.get_experiment(self.experiment.record_id), self.experiment)

        with closing(sqlite3.connect(self.database_path)) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM pap_pilot_metadata"))
            serialized = connection.execute("SELECT record_json FROM experiments").fetchone()[0]
        payload = json.loads(serialized)
        self.assertEqual(metadata, {"schema_id": EXPERIMENT_STORE_SCHEMA_ID, "schema_version": str(EXPERIMENT_STORE_SCHEMA_VERSION)})
        self.assertEqual((payload["format"], payload["format_version"]), (EXPERIMENT_STORE_RECORD_FORMAT, EXPERIMENT_STORE_RECORD_FORMAT_VERSION))
        self.assertEqual(payload["record"]["record_type"], "experiment")

    def test_append_replay_and_reopen_preserve_correction_history(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original wording"), 1, record_id="event:problem-original")
        correction = self._event(
            ExperimentEventType.PROBLEM_RECORDED,
            ProblemRecordedPayload("Corrected wording"),
            2,
            record_id="event:problem-correction",
            correction_of_event_id=original.record_id,
        )
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_event(original)
            store.append_event(correction)
            replayed = store.replay(self.experiment.record_id)

        self.assertEqual(replayed.experiment, self.experiment)
        self.assertEqual(replayed.history, (original, correction))
        self.assertEqual(replayed.corrected_event_ids, (original.record_id,))
        self.assertEqual(replayed.effective_events, (correction,))
        self.assertEqual(replayed.events(ExperimentEventType.PROBLEM_RECORDED, effective_only=False), (original, correction))
        self.assertEqual(replayed.latest_event(ExperimentEventType.PROBLEM_RECORDED), correction)
        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.replay(self.experiment.record_id), replayed)

    def test_every_s25_payload_roundtrips_through_sqlite_in_ledger_order(self) -> None:
        proposal = self._proposal()
        action = ExperimentActionPayload("User decision", 1_788_400_000_000)
        payloads = {
            ExperimentEventType.PROBLEM_RECORDED: ProblemRecordedPayload("Repeated awakenings"),
            ExperimentEventType.HYPOTHESIS_DRAFTED: HypothesisDraftedPayload("PS Min may contribute", ("Normal variability", "Mask leak")),
            ExperimentEventType.EXPERIMENT_PROPOSED: ExperimentProposedPayload(proposal),
            ExperimentEventType.EXPERIMENT_ACCEPTED: ExperimentDecisionPayload("event:proposal", "Accepted"),
            ExperimentEventType.EXPERIMENT_REJECTED: ExperimentDecisionPayload("event:proposal", "Rejected alternative"),
            ExperimentEventType.EXPERIMENT_REVISED: ExperimentRevisedPayload("event:proposal", proposal),
            ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED: SettingChangeConfirmedPayload("event:accepted", self.change, 1_788_350_000_000),
            ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED: SleepJournalEntryRecordedPayload("journal:one", "night:intervention"),
            ExperimentEventType.CONFOUNDER_RECORDED: ObservationRecordedPayload("Travel", 1_788_360_000_000, "night:intervention"),
            ExperimentEventType.ADVERSE_EFFECT_RECORDED: ObservationRecordedPayload("Discomfort", 1_788_370_000_000, "night:intervention"),
            ExperimentEventType.EXPERIMENT_STOPPED: action,
            ExperimentEventType.EXPERIMENT_EXTENDED: ExperimentActionPayload("More data", 1_788_400_000_000, "2026-09-10"),
            ExperimentEventType.EXPERIMENT_KEPT: action,
            ExperimentEventType.EXPERIMENT_REVERTED: action,
            ExperimentEventType.EVALUATION_ISSUED: EvaluationIssuedPayload("evaluation:one"),
            ExperimentEventType.EVALUATION_SUPERSEDED: EvaluationSupersededPayload("event:evaluation-one", "evaluation:two"),
            ExperimentEventType.NOTE_RECORDED: NoteRecordedPayload("Retained note", "event:evaluation-one"),
        }
        record_ids = {
            ExperimentEventType.PROBLEM_RECORDED: "event:problem",
            ExperimentEventType.HYPOTHESIS_DRAFTED: "event:hypothesis",
            ExperimentEventType.EXPERIMENT_PROPOSED: "event:proposal",
            ExperimentEventType.EXPERIMENT_ACCEPTED: "event:accepted",
            ExperimentEventType.EVALUATION_ISSUED: "event:evaluation-one",
        }
        expected = tuple(
            self._event(event_type, payloads[event_type], sequence, record_id=record_ids.get(event_type))
            for sequence, event_type in enumerate(ExperimentEventType, start=1)
        )

        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            for event in expected:
                if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED:
                    store.append_journal_entry(
                        event,
                        SleepJournalEntry(
                            record_id="journal:one",
                            night_record_id="night:intervention",
                            reported_at_ms=1_788_355_000_000,
                            reported_by="user:local",
                            awakenings_count=2,
                            sleep_quality=4,
                            morning_energy=4,
                            daytime_tiredness=2,
                            confounder_status=ConfounderReportStatus.NONE_REPORTED,
                            confounders=(),
                            original_note=None,
                            source_provenance_ids=("provenance:user",),
                        ),
                    )
                else:
                    store.append_event(event)
            self.assertEqual(store.read_history(self.experiment.record_id), expected)
            self.assertEqual(store.replay(self.experiment.record_id).effective_events, expected)

        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.read_history(self.experiment.record_id), expected)

    def test_failed_append_rolls_back_without_changing_prior_history(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original"), 1, record_id="event:problem")
        skipped = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Skipped"), 3)
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_event(original)
            with self.assertRaises(ExperimentStoreError):
                store.append_event(skipped)
            self.assertEqual(store.read_history(self.experiment.record_id), (original,))

    def test_stale_second_correction_is_rejected_and_chain_correction_replays(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original"), 1, record_id="event:problem")
        first_correction = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("First correction"), 2, record_id="event:correction-one", correction_of_event_id=original.record_id)
        stale = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Ambiguous correction"), 3, record_id="event:correction-stale", correction_of_event_id=original.record_id)
        chained = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Final correction"), 3, record_id="event:correction-two", correction_of_event_id=first_correction.record_id)

        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_event(original)
            store.append_event(first_correction)
            with self.assertRaises(ExperimentStoreError):
                store.append_event(stale)
            store.append_event(chained)
            replayed = store.replay(self.experiment.record_id)

        self.assertEqual(replayed.history, (original, first_correction, chained))
        self.assertEqual(replayed.corrected_event_ids, (original.record_id, first_correction.record_id))
        self.assertEqual(replayed.effective_events, (chained,))

    def test_duplicate_identity_and_event_are_rejected_without_replacement(self) -> None:
        event = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original"), 1, record_id="event:problem")
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            with self.assertRaises(ExperimentStoreError):
                store.create_experiment(replace(self.experiment, title="Replacement"))
            store.append_event(event)
            with self.assertRaises(ExperimentStoreError):
                store.append_event(replace(event, sequence_number=2, payload=ProblemRecordedPayload("Replacement")))
            self.assertEqual(store.get_experiment(self.experiment.record_id), self.experiment)
            self.assertEqual(store.read_history(self.experiment.record_id), (event,))

    def test_sqlite_triggers_reject_update_delete_and_replace_statements(self) -> None:
        event = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original"), 1, record_id="event:problem")
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_event(event)
            self.assertFalse(hasattr(store, "update_experiment"))
            self.assertFalse(hasattr(store, "update_event"))
            self.assertFalse(hasattr(store, "delete_experiment"))
            self.assertFalse(hasattr(store, "delete_event"))

        with closing(sqlite3.connect(self.database_path)) as inspection:
            experiment_row = inspection.execute("SELECT record_id, created_at_ms, record_json FROM experiments").fetchone()
            event_row = inspection.execute("SELECT record_id, experiment_record_id, sequence_number, event_type, recorded_at_ms, correction_of_event_id, record_json FROM experiment_events").fetchone()
        statements = (
            ("UPDATE experiments SET record_json = ? WHERE record_id = ?", ("{}", self.experiment.record_id)),
            ("DELETE FROM experiments WHERE record_id = ?", (self.experiment.record_id,)),
            ("INSERT OR REPLACE INTO experiments (record_id, created_at_ms, record_json) VALUES (?, ?, ?)", experiment_row),
            ("UPDATE experiment_events SET record_json = ? WHERE record_id = ?", ("{}", event.record_id)),
            ("DELETE FROM experiment_events WHERE record_id = ?", (event.record_id,)),
            ("INSERT OR REPLACE INTO experiment_events (record_id, experiment_record_id, sequence_number, event_type, recorded_at_ms, correction_of_event_id, record_json) VALUES (?, ?, ?, ?, ?, ?, ?)", event_row),
        )
        for statement, parameters in statements:
            with self.subTest(statement=statement.split()[0:3]), closing(sqlite3.connect(self.database_path)) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement, parameters)
                connection.rollback()

        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.get_experiment(self.experiment.record_id), self.experiment)
            self.assertEqual(reopened.read_history(self.experiment.record_id), (event,))

    def test_foreign_database_is_rejected_without_modification(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
            connection.commit()
        original = self.database_path.read_bytes()

        with self.assertRaisesRegex(ExperimentStoreError, "not an exact supported"):
            ExperimentStore(self.database_path)

        self.assertEqual(self.database_path.read_bytes(), original)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM sentinel").fetchone(), ("unchanged",))
            self.assertNotIn("experiments", {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")})

    def test_wrong_filename_is_rejected_before_sqlite_creates_a_file(self) -> None:
        wrong_path = self.database_path.with_name("oscar.db")

        with self.assertRaisesRegex(ExperimentStoreError, LOCAL_EXPERIMENT_DATABASE_FILENAME):
            ExperimentStore(wrong_path)

        self.assertFalse(wrong_path.exists())

    def test_unsupported_schema_or_missing_trigger_is_rejected_on_reopen(self) -> None:
        with ExperimentStore(self.database_path):
            pass
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("UPDATE pap_pilot_metadata SET value = '999' WHERE key = 'schema_version'")
            connection.commit()
        with self.assertRaisesRegex(ExperimentStoreError, "unsupported"):
            ExperimentStore(self.database_path)

        self.database_path.unlink()
        with ExperimentStore(self.database_path):
            pass
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DROP TRIGGER experiment_events_no_delete")
            connection.commit()
        with self.assertRaisesRegex(ExperimentStoreError, "missing an append-only"):
            ExperimentStore(self.database_path)

    def test_missing_experiment_and_closed_store_fail_explicitly(self) -> None:
        store = ExperimentStore(self.database_path)
        with self.assertRaisesRegex(ExperimentStoreError, "does not exist"):
            store.replay("experiment:missing")
        store.close()
        store.close()
        with self.assertRaisesRegex(ExperimentStoreError, "closed"):
            store.get_experiment(self.experiment.record_id)

    def test_s25_history_validation_rejects_multiple_corrections_of_stale_event(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original"), 1, record_id="event:problem")
        first = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("First"), 2, correction_of_event_id=original.record_id)
        second = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Second"), 3, correction_of_event_id=original.record_id)
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.experiment)
            store.append_event(original)
            store.append_event(first)
            with self.assertRaisesRegex(ExperimentStoreError, "could not be appended"):
                store.append_event(second)

        with self.assertRaisesRegex(ExperimentModelError, "already corrected"):
            validate_experiment_history(self.experiment, (original, first, second))

    def _proposal(self) -> ExperimentProposal:
        return ExperimentProposal(
            problem_event_id="event:problem",
            hypothesis_event_id="event:hypothesis",
            baseline_local_dates=("2026-08-28", "2026-08-29"),
            baseline_settings=self.baseline_settings,
            proposed_change=self.change,
            settings_held_fixed=tuple(setting for setting in self.baseline_settings if setting.name != "ps_min"),
            evidence_record_ids=("night:baseline", "session:baseline", "signal:flow"),
            representative_intervals=(ExperimentEvidenceInterval("night:baseline", "session:baseline", 1_000, 61_000, ("night:baseline", "session:baseline", "signal:flow")),),
            expected_objective_effects=("Lower Mask Pressure above fixed EPAP",),
            expected_subjective_effects=("Fewer remembered awakenings",),
            minimum_valid_nights=3,
            invalid_night_criteria=("Insufficient required signal coverage",),
            possible_adverse_effects=("Reduced ventilatory support",),
            stop_conditions=("Material worsening",),
            revert_conditions=("Sustained worsening",),
        )

    def _event(
        self,
        event_type: ExperimentEventType,
        payload,
        sequence_number: int,
        *,
        record_id: str | None = None,
        correction_of_event_id: str | None = None,
    ) -> ExperimentEvent:
        return ExperimentEvent(
            record_id=record_id or f"event:{sequence_number}:{event_type.value}",
            experiment_record_id=self.experiment.record_id,
            sequence_number=sequence_number,
            event_type=event_type,
            recorded_at_ms=1_788_300_000_000 + sequence_number,
            recorded_by="user:local",
            payload=payload,
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=(self.experiment.record_id,),
            source_provenance_ids=("provenance:user",),
            correction_of_event_id=correction_of_event_id,
        )


if __name__ == "__main__":
    unittest.main()
