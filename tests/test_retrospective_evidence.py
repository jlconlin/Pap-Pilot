"""Focused tests for retrospective per-night user-evidence intake."""

from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sqlite3
import unittest

from pap_pilot.engine import (
    ConfounderKind,
    ConfounderReportStatus,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentRecord,
    ExperimentStore,
    ExperimentStoreError,
    RetrospectiveEvidenceError,
    RetrospectiveEvidenceStatus,
    RetrospectiveNightEvidenceInput,
    RetrospectiveObservation,
    SleepJournalConfounder,
    SleepJournalEntry,
    SleepJournalEntryRecordedPayload,
    SourceClass,
    build_retrospective_user_evidence,
    record_retrospective_protocol,
    record_retrospective_user_evidence,
)

from tests import test_retrospective_protocol


class RetrospectiveEvidenceTests(unittest.TestCase):
    """Use only the synthetic selected cohort and temporary local stores."""

    def setUp(self) -> None:
        fixture = test_retrospective_protocol.RetrospectiveProtocolTests(
            methodName="test_atomically_persists_exact_accepted_proposal_and_confirmed_boundary"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        with ExperimentStore(self.fixture.database_path) as store:
            self.protocol_replay = record_retrospective_protocol(
                store,
                self.fixture.fixture.experiment.record_id,
                self.fixture.cohort,
                self.fixture.protocol,
            )
        self.inputs = self._inputs()

    def _inputs(self) -> tuple[RetrospectiveNightEvidenceInput, ...]:
        first_night, second_night = self.fixture.cohort.nights
        note = "  Woke twice.\nFelt steadier after breakfast.  "
        journal = SleepJournalEntry(
            record_id="journal:retrospective:first",
            night_record_id=first_night.record_id,
            reported_at_ms=1_900_000_001_000,
            reported_by="user:local",
            awakenings_count=2,
            sleep_quality=4,
            morning_energy=4,
            daytime_tiredness=None,
            confounder_status=ConfounderReportStatus.REPORTED,
            confounders=(
                SleepJournalConfounder(
                    ConfounderKind.TRAVEL,
                    "  Arrived home late.  ",
                ),
            ),
            original_note=note,
            source_provenance_ids=("provenance:user:journal:first",),
        )
        confounder = RetrospectiveObservation(
            description="  Unusually late bedtime.\nNo schedule alarm.  ",
            observed_at_ms=first_night.sessions[0].start_time_ms,
            recorded_at_ms=1_900_000_001_100,
            recorded_by="user:local",
            source_record_ids=("user-history:confounder:first",),
            source_provenance_ids=("provenance:user:confounder:first",),
        )
        adverse = RetrospectiveObservation(
            description="  Mild morning bloating.  ",
            observed_at_ms=first_night.sessions[-1].end_time_ms,
            recorded_at_ms=1_900_000_001_200,
            recorded_by="user:local",
            source_record_ids=("user-history:adverse:first",),
            source_provenance_ids=("provenance:user:adverse:first",),
        )
        return (
            RetrospectiveNightEvidenceInput(
                night_record_id=first_night.record_id,
                journal_status=RetrospectiveEvidenceStatus.REPORTED,
                journal_entry=journal,
                confounder_status=RetrospectiveEvidenceStatus.REPORTED,
                confounders=(confounder,),
                adverse_effect_status=RetrospectiveEvidenceStatus.REPORTED,
                adverse_effects=(adverse,),
                recorded_at_ms=1_900_000_001_300,
                recorded_by="user:local",
                source_record_ids=("user-history:first",),
                source_provenance_ids=("provenance:user:first",),
            ),
            RetrospectiveNightEvidenceInput(
                night_record_id=second_night.record_id,
                journal_status=RetrospectiveEvidenceStatus.UNAVAILABLE,
                journal_entry=None,
                confounder_status=RetrospectiveEvidenceStatus.NONE_REPORTED,
                confounders=(),
                adverse_effect_status=RetrospectiveEvidenceStatus.NOT_REPORTED,
                adverse_effects=(),
                recorded_at_ms=1_900_000_001_400,
                recorded_by="user:local",
                source_record_ids=("user-history:second",),
                source_provenance_ids=("provenance:user:second",),
            ),
        )

    def test_atomic_replay_preserves_exact_per_night_evidence_and_all_statuses(self) -> None:
        with ExperimentStore(self.fixture.database_path) as store:
            replayed = record_retrospective_user_evidence(
                store,
                self.fixture.fixture.experiment.record_id,
                self.fixture.cohort,
                self.inputs,
            )

        self.assertEqual(
            replayed.history[: len(self.protocol_replay.history)],
            self.protocol_replay.history,
        )
        self.assertEqual(
            tuple(event.event_type for event in replayed.history[-3:]),
            (
                ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED,
                ExperimentEventType.CONFOUNDER_RECORDED,
                ExperimentEventType.ADVERSE_EFFECT_RECORDED,
            ),
        )
        first, second = replayed.effective_retrospective_evidence
        self.assertEqual(first.journal_entry, self.inputs[0].journal_entry)
        self.assertEqual(
            first.journal_entry.original_note,
            "  Woke twice.\nFelt steadier after breakfast.  ",
        )
        self.assertEqual(
            first.journal_entry.confounders[0].details,
            "  Arrived home late.  ",
        )
        self.assertEqual(
            first.confounders[0].description,
            "  Unusually late bedtime.\nNo schedule alarm.  ",
        )
        self.assertEqual(first.adverse_effects[0].description, "  Mild morning bloating.  ")
        event_ids = {event.record_id for event in replayed.history}
        for record in (first, second):
            self.assertTrue(
                {
                    self.fixture.fixture.experiment.record_id,
                    self.fixture.cohort.record_id,
                    record.night_record_id,
                }.issubset(record.source_record_ids)
            )
            self.assertTrue(
                set(
                    (
                        *((record.journal_event_id,) if record.journal_event_id else ()),
                        *record.confounder_event_ids,
                        *record.adverse_effect_event_ids,
                    )
                ).issubset(event_ids)
            )
        self.assertEqual(
            (
                first.journal_status,
                first.confounder_status,
                second.journal_status,
                second.confounder_status,
                second.adverse_effect_status,
            ),
            (
                RetrospectiveEvidenceStatus.REPORTED,
                RetrospectiveEvidenceStatus.REPORTED,
                RetrospectiveEvidenceStatus.UNAVAILABLE,
                RetrospectiveEvidenceStatus.NONE_REPORTED,
                RetrospectiveEvidenceStatus.NOT_REPORTED,
            ),
        )
        self.assertIsNone(second.journal_entry)
        self.assertEqual(second.confounders, ())
        self.assertEqual(second.adverse_effects, ())
        with ExperimentStore(self.fixture.database_path) as reopened:
            self.assertEqual(
                reopened.replay(self.fixture.fixture.experiment.record_id),
                replayed,
            )

    def test_build_is_order_independent_and_deterministic(self) -> None:
        forward = build_retrospective_user_evidence(
            self.protocol_replay,
            self.fixture.cohort,
            self.inputs,
        )
        reversed_input = build_retrospective_user_evidence(
            self.protocol_replay,
            self.fixture.cohort,
            tuple(reversed(self.inputs)),
        )
        self.assertEqual(forward, reversed_input)
        self.assertEqual(
            tuple(record.cohort_night_index for record in forward.night_evidence),
            (0, 1),
        )
        journal_only_confounder = replace(self.inputs[0], confounders=())
        journal_only = build_retrospective_user_evidence(
            self.protocol_replay,
            self.fixture.cohort,
            (journal_only_confounder, self.inputs[1]),
        )
        self.assertEqual(
            journal_only.night_evidence[0].confounder_status,
            RetrospectiveEvidenceStatus.REPORTED,
        )
        self.assertEqual(journal_only.night_evidence[0].confounders, ())
        changed_source = replace(
            self.inputs[0],
            source_provenance_ids=("provenance:user:changed",),
        )
        changed = build_retrospective_user_evidence(
            self.protocol_replay,
            self.fixture.cohort,
            (changed_source, self.inputs[1]),
        )
        self.assertNotEqual(
            tuple(event.record_id for event in forward.events),
            tuple(event.record_id for event in changed.events),
        )
        self.assertNotEqual(
            forward.night_evidence[0].record_id,
            changed.night_evidence[0].record_id,
        )

    def test_requires_exact_selected_cohort_coverage(self) -> None:
        invalid_inputs = (
            ("every selected cohort night", self.inputs[:1]),
            ("only once", (self.inputs[0], self.inputs[0])),
            (
                "no other night",
                (
                    self.inputs[0],
                    replace(self.inputs[1], night_record_id="night:outside"),
                ),
            ),
        )
        for message, inputs in invalid_inputs:
            with self.subTest(message=message), self.assertRaisesRegex(
                RetrospectiveEvidenceError,
                message,
            ):
                build_retrospective_user_evidence(
                    self.protocol_replay,
                    self.fixture.cohort,
                    inputs,
                )

    def test_all_unreported_states_persist_without_fabricated_events(self) -> None:
        unavailable = tuple(
            RetrospectiveNightEvidenceInput(
                night_record_id=night.record_id,
                journal_status=RetrospectiveEvidenceStatus.UNAVAILABLE,
                journal_entry=None,
                confounder_status=RetrospectiveEvidenceStatus.NOT_REPORTED,
                confounders=(),
                adverse_effect_status=RetrospectiveEvidenceStatus.NONE_REPORTED,
                adverse_effects=(),
                recorded_at_ms=1_900_000_002_000 + index,
                recorded_by="user:local",
                source_record_ids=(f"user-history:unavailable:{index}",),
                source_provenance_ids=(f"provenance:user:unavailable:{index}",),
            )
            for index, night in enumerate(self.fixture.cohort.nights)
        )
        batch = build_retrospective_user_evidence(
            self.protocol_replay,
            self.fixture.cohort,
            unavailable,
        )
        self.assertEqual(batch.events, ())
        self.assertEqual(batch.journal_entries, ())
        with ExperimentStore(self.fixture.database_path) as store:
            replayed = record_retrospective_user_evidence(
                store,
                self.fixture.fixture.experiment.record_id,
                self.fixture.cohort,
                unavailable,
            )
        self.assertEqual(replayed.history, self.protocol_replay.history)
        self.assertEqual(
            tuple(
                (
                    record.journal_status,
                    record.confounder_status,
                    record.adverse_effect_status,
                )
                for record in replayed.effective_retrospective_evidence
            ),
            (
                (
                    RetrospectiveEvidenceStatus.UNAVAILABLE,
                    RetrospectiveEvidenceStatus.NOT_REPORTED,
                    RetrospectiveEvidenceStatus.NONE_REPORTED,
                ),
                (
                    RetrospectiveEvidenceStatus.UNAVAILABLE,
                    RetrospectiveEvidenceStatus.NOT_REPORTED,
                    RetrospectiveEvidenceStatus.NONE_REPORTED,
                ),
            ),
        )

    def test_refuses_status_content_and_night_inconsistency(self) -> None:
        first = self.inputs[0]
        second_night = self.fixture.cohort.nights[1]
        cases = (
            (
                "requires its exact entry",
                lambda: replace(first, journal_entry=None),
            ),
            (
                "selected cohort night",
                lambda: replace(
                    first,
                    journal_entry=replace(
                        first.journal_entry,
                        night_record_id=second_night.record_id,
                    ),
                ),
            ),
            (
                "conflicts",
                lambda: replace(
                    first,
                    confounder_status=RetrospectiveEvidenceStatus.NONE_REPORTED,
                    confounders=(),
                ),
            ),
            (
                "cannot carry observations",
                lambda: replace(
                    first,
                    adverse_effect_status=RetrospectiveEvidenceStatus.NONE_REPORTED,
                ),
            ),
        )
        for message, build in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                RetrospectiveEvidenceError,
                message,
            ):
                candidate = build()
                build_retrospective_user_evidence(
                    self.protocol_replay,
                    self.fixture.cohort,
                    (candidate, self.inputs[1]),
                )

    def test_requires_linked_protocol_and_refuses_second_intake(self) -> None:
        empty_path = Path(self.fixture.temporary_directory.name) / "empty" / "pap_pilot.sqlite3"
        empty_path.parent.mkdir()
        with ExperimentStore(empty_path) as store:
            store.create_experiment(self.fixture.fixture.experiment)
            store.append_events(self.fixture.fixture.history)
            without_protocol = store.replay(self.fixture.fixture.experiment.record_id)
        with self.assertRaisesRegex(RetrospectiveEvidenceError, "accepted protocol"):
            build_retrospective_user_evidence(
                without_protocol,
                self.fixture.cohort,
                self.inputs,
            )

        with ExperimentStore(self.fixture.database_path) as store:
            first = record_retrospective_user_evidence(
                store,
                self.fixture.fixture.experiment.record_id,
                self.fixture.cohort,
                self.inputs,
            )
            with self.assertRaisesRegex(RetrospectiveEvidenceError, "already contains"):
                record_retrospective_user_evidence(
                    store,
                    self.fixture.fixture.experiment.record_id,
                    self.fixture.cohort,
                    self.inputs,
                )
            self.assertEqual(store.replay(self.fixture.fixture.experiment.record_id), first)

    def test_database_collision_rolls_back_entire_intake(self) -> None:
        other = ExperimentRecord(
            record_id="experiment:other",
            title="Other experiment",
            created_at_ms=1,
            created_by="user:local",
            source_provenance_ids=("provenance:user:other",),
        )
        journal = self.inputs[0].journal_entry
        other_event = ExperimentEvent(
            record_id="event:other-journal",
            experiment_record_id=other.record_id,
            sequence_number=1,
            event_type=ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED,
            recorded_at_ms=journal.reported_at_ms,
            recorded_by=journal.reported_by,
            payload=SleepJournalEntryRecordedPayload(
                journal.record_id,
                journal.night_record_id,
            ),
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=(other.record_id, journal.night_record_id),
            source_provenance_ids=journal.source_provenance_ids,
        )
        with ExperimentStore(self.fixture.database_path) as store:
            store.create_experiment(other)
            store.append_journal_entry(other_event, journal)
            before = store.replay(self.fixture.fixture.experiment.record_id)
            with self.assertRaisesRegex(ExperimentStoreError, "atomically"):
                record_retrospective_user_evidence(
                    store,
                    self.fixture.fixture.experiment.record_id,
                    self.fixture.cohort,
                    self.inputs,
                )
            self.assertEqual(
                store.replay(self.fixture.fixture.experiment.record_id),
                before,
            )

    def test_version_two_store_migrates_and_evidence_rows_are_append_only(self) -> None:
        with closing(sqlite3.connect(self.fixture.database_path)) as connection:
            connection.execute("DROP TRIGGER retrospective_night_evidence_no_update")
            connection.execute("DROP TRIGGER retrospective_night_evidence_no_delete")
            connection.execute("DROP TRIGGER retrospective_night_evidence_no_replace")
            connection.execute("DROP TABLE retrospective_night_evidence")
            connection.execute(
                "UPDATE pap_pilot_metadata SET value = '2' WHERE key = 'schema_version'"
            )
            connection.commit()
        with ExperimentStore(self.fixture.database_path) as migrated:
            replayed = record_retrospective_user_evidence(
                migrated,
                self.fixture.fixture.experiment.record_id,
                self.fixture.cohort,
                self.inputs,
            )
        record = replayed.effective_retrospective_evidence[0]
        with closing(sqlite3.connect(self.fixture.database_path)) as connection:
            row = connection.execute(
                "SELECT record_id, experiment_record_id, cohort_record_id, cohort_night_index, night_record_id, recorded_at_ms, recorded_by, record_json FROM retrospective_night_evidence WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
        statements = (
            (
                "UPDATE retrospective_night_evidence SET record_json = '{}' WHERE record_id = ?",
                (record.record_id,),
            ),
            (
                "DELETE FROM retrospective_night_evidence WHERE record_id = ?",
                (record.record_id,),
            ),
            (
                "INSERT OR REPLACE INTO retrospective_night_evidence (record_id, experiment_record_id, cohort_record_id, cohort_night_index, night_record_id, recorded_at_ms, recorded_by, record_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            ),
        )
        for statement, parameters in statements:
            with self.subTest(statement=statement.split()[0]), closing(
                sqlite3.connect(self.fixture.database_path)
            ) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement, parameters)

    def test_input_observations_and_replayed_records_are_frozen(self) -> None:
        batch = build_retrospective_user_evidence(
            self.protocol_replay,
            self.fixture.cohort,
            self.inputs,
        )
        with self.assertRaises(FrozenInstanceError):
            self.inputs[0].recorded_by = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            self.inputs[0].confounders[0].description = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            batch.night_evidence[0].record_id = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
