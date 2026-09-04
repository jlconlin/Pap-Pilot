"""Focused tests for accepted retrospective protocol persistence."""

from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pap_pilot.adapter import OscarCohortSelection, extract_normalized_oscar_cohort
from pap_pilot.engine import (
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentSetting,
    ExperimentSettingChange,
    ExperimentStore,
    ExperimentStoreError,
    NoteRecordedPayload,
    RetrospectiveCohortEvidence,
    RetrospectiveProtocolError,
    RetrospectiveProtocolInput,
    SettingChangeConfirmedPayload,
    SourceClass,
    build_retrospective_protocol_events,
    record_retrospective_protocol,
    reconstruct_ps_min_experiment_fixture,
)

from tests import test_oscar_cohort


_BOUNDARY_MS = 1_800_050_000_000


class RetrospectiveProtocolTests(unittest.TestCase):
    """Use synthetic cohort and local-store fixtures only."""

    def setUp(self) -> None:
        cohort_fixture = test_oscar_cohort.OscarCohortTests(
            methodName="test_extracts_explicit_reproducible_multi_night_cohort_without_writing_source"
        )
        cohort_fixture.setUp()
        self.addCleanup(cohort_fixture.doCleanups)
        extracted = extract_normalized_oscar_cohort(
            cohort_fixture.database_path,
            OscarCohortSelection((100, 101, 102)),
        )
        self.cohort = RetrospectiveCohortEvidence(
            record_id=extracted.record_id,
            nights=extracted.nights,
            source_record_ids=extracted.source_record_ids,
        )
        self.fixture = reconstruct_ps_min_experiment_fixture()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = (
            Path(self.temporary_directory.name) / "pap_pilot.sqlite3"
        )
        self._initialize_store(self.database_path)
        self.proposal = self._proposal()
        self.protocol = self._protocol(self.proposal)

    def _initialize_store(self, path: Path) -> None:
        with ExperimentStore(path) as store:
            store.create_experiment(self.fixture.experiment)
            store.append_events(self.fixture.history)

    def _proposal(self) -> ExperimentProposal:
        baseline_night = self.cohort.nights[0]
        baseline_session = baseline_night.sessions[0]
        baseline_settings = tuple(
            ExperimentSetting(setting.name, setting.value, setting.unit)
            for setting in baseline_session.settings
        )
        flow = next(
            signal
            for signal in baseline_session.signals
            if signal.signal_kind == "flow_rate"
        )
        segment = flow.segments[0]
        interval_sources = (
            baseline_night.record_id,
            baseline_session.record_id,
            flow.record_id,
            segment.record_id,
        )
        return ExperimentProposal(
            problem_event_id=self.fixture.history[0].record_id,
            hypothesis_event_id=self.fixture.history[1].record_id,
            baseline_local_dates=(baseline_night.local_date,),
            baseline_settings=baseline_settings,
            proposed_change=self.fixture.known_change,
            settings_held_fixed=tuple(
                setting for setting in baseline_settings if setting.name != "ps_min"
            ),
            evidence_record_ids=(self.cohort.record_id, *interval_sources),
            representative_intervals=(
                ExperimentEvidenceInterval(
                    night_record_id=baseline_night.record_id,
                    session_record_id=baseline_session.record_id,
                    start_time_ms=segment.start_time_ms,
                    end_time_ms=segment.end_time_ms,
                    source_record_ids=interval_sources,
                ),
            ),
            expected_objective_effects=(
                "Lower independently calculated Mask Pressure above fixed EPAP",
            ),
            expected_subjective_effects=("Fewer remembered awakenings",),
            minimum_valid_nights=3,
            invalid_night_criteria=(
                "Insufficient required signal or quality evidence",
            ),
            possible_adverse_effects=("Reduced ventilatory support",),
            stop_conditions=("Material worsening of breathing or symptoms",),
            revert_conditions=("Sustained subjective or objective worsening",),
        )

    def _protocol(self, proposal: ExperimentProposal) -> RetrospectiveProtocolInput:
        return RetrospectiveProtocolInput(
            proposal=proposal,
            user_accepted=True,
            acceptance_rationale="This exactly records the retrospective protocol I intended to evaluate.",
            confirmed_change=self.fixture.known_change,
            boundary_user_confirmed=True,
            applied_at_ms=_BOUNDARY_MS,
            proposal_recorded_at_ms=1_900_000_000_000,
            accepted_at_ms=1_900_000_000_001,
            confirmed_at_ms=1_900_000_000_002,
            recorded_by="user:local",
            user_source_record_ids=("user-confirmation:synthetic",),
            user_provenance_ids=("provenance:user:synthetic",),
        )

    def test_atomically_persists_exact_accepted_proposal_and_confirmed_boundary(self) -> None:
        with ExperimentStore(self.database_path) as store:
            before = store.replay(self.fixture.experiment.record_id)
            replayed = record_retrospective_protocol(
                store,
                self.fixture.experiment.record_id,
                self.cohort,
                self.protocol,
            )

        self.assertEqual(replayed.history[:2], before.history)
        self.assertEqual(len(replayed.history), 5)
        proposal, acceptance, confirmation = replayed.history[-3:]
        self.assertEqual(proposal.event_type, ExperimentEventType.EXPERIMENT_PROPOSED)
        self.assertEqual(proposal.payload, ExperimentProposedPayload(self.proposal))
        self.assertEqual(proposal.source_class, SourceClass.COMPANION_DERIVED)
        self.assertIn(self.cohort.record_id, proposal.source_record_ids)
        self.assertEqual(acceptance.event_type, ExperimentEventType.EXPERIMENT_ACCEPTED)
        self.assertEqual(
            acceptance.payload,
            ExperimentDecisionPayload(
                proposal.record_id,
                self.protocol.acceptance_rationale,
            ),
        )
        self.assertEqual(acceptance.source_class, SourceClass.USER_REPORTED)
        self.assertEqual(
            confirmation.event_type,
            ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED,
        )
        self.assertEqual(
            confirmation.payload,
            SettingChangeConfirmedPayload(
                acceptance.record_id,
                self.fixture.known_change,
                _BOUNDARY_MS,
            ),
        )
        self.assertEqual(confirmation.source_class, SourceClass.USER_REPORTED)
        self.assertIn(self.cohort.record_id, confirmation.source_record_ids)
        self.assertEqual(replayed.effective_events, replayed.history)
        self.assertEqual(
            replayed.latest_event(ExperimentEventType.EXPERIMENT_PROPOSED),
            proposal,
        )
        self.assertEqual(
            replayed.latest_event(ExperimentEventType.EXPERIMENT_ACCEPTED),
            acceptance,
        )
        self.assertEqual(
            replayed.latest_event(
                ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED
            ),
            confirmation,
        )

        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(
                reopened.replay(self.fixture.experiment.record_id),
                replayed,
            )

    def test_event_identity_and_replay_are_deterministic_across_stores(self) -> None:
        second_path = Path(self.temporary_directory.name) / "second" / "pap_pilot.sqlite3"
        second_path.parent.mkdir()
        self._initialize_store(second_path)

        with ExperimentStore(self.database_path) as store:
            initial = store.replay(self.fixture.experiment.record_id)
        results = []
        for path in (self.database_path, second_path):
            with ExperimentStore(path) as store:
                results.append(
                    record_retrospective_protocol(
                        store,
                        self.fixture.experiment.record_id,
                        self.cohort,
                        self.protocol,
                    )
                )

        self.assertEqual(results[0], results[1])
        self.assertEqual(
            tuple(event.record_id for event in results[0].history[-3:]),
            tuple(event.record_id for event in results[1].history[-3:]),
        )
        changed_evidence = replace(
            self.protocol,
            user_source_record_ids=("user-confirmation:different",),
        )
        original_events = build_retrospective_protocol_events(
            initial,
            self.cohort,
            self.protocol,
        )
        changed_events = build_retrospective_protocol_events(
            initial,
            self.cohort,
            changed_evidence,
        )
        self.assertEqual(original_events[0].record_id, changed_events[0].record_id)
        self.assertNotEqual(original_events[1].record_id, changed_events[1].record_id)
        self.assertNotEqual(original_events[2].record_id, changed_events[2].record_id)

    def test_refuses_to_infer_acceptance_confirmation_or_change(self) -> None:
        invalid_inputs = (
            ("explicitly accepted", {"user_accepted": False}),
            ("explicitly user-confirmed", {"boundary_user_confirmed": False}),
            (
                "exactly match",
                {
                    "confirmed_change": ExperimentSettingChange(
                        ExperimentSetting("ps_min", 2.0, "cm H₂O"),
                        ExperimentSetting("ps_min", 0.5, "cm H₂O"),
                    )
                },
            ),
        )
        for message, changes in invalid_inputs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RetrospectiveProtocolError, message):
                    invalid = replace(self.protocol, **changes)
                    with ExperimentStore(self.database_path) as store:
                        record_retrospective_protocol(
                            store,
                            self.fixture.experiment.record_id,
                            self.cohort,
                            invalid,
                        )
                with ExperimentStore(self.database_path) as store:
                    self.assertEqual(
                        store.read_history(self.fixture.experiment.record_id),
                        self.fixture.history,
                    )

    def test_rejects_boundary_or_settings_inconsistent_with_selected_cohort(self) -> None:
        inside_session = replace(
            self.protocol,
            applied_at_ms=self.cohort.nights[0].sessions[0].start_time_ms + 1,
        )
        after_cohort = replace(
            self.protocol,
            applied_at_ms=self.cohort.nights[-1].sessions[-1].end_time_ms + 1,
        )
        incomplete_fixed = tuple(
            setting
            for setting in self.proposal.settings_held_fixed
            if setting.name != "therapy_mode_code"
        )
        incomplete_proposal = replace(
            self.proposal,
            settings_held_fixed=incomplete_fixed,
        )
        cases = (
            ("inside a selected therapy session", inside_session),
            ("conflict", after_cohort),
            (
                "hold every setting except PS Min fixed",
                replace(self.protocol, proposal=incomplete_proposal),
            ),
        )
        for message, value in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                RetrospectiveProtocolError,
                message,
            ):
                with ExperimentStore(self.database_path) as store:
                    record_retrospective_protocol(
                        store,
                        self.fixture.experiment.record_id,
                        self.cohort,
                        value,
                    )
        with ExperimentStore(self.database_path) as store:
            self.assertEqual(
                store.read_history(self.fixture.experiment.record_id),
                self.fixture.history,
            )

    def test_rejects_unlinked_cohort_baseline_or_interval(self) -> None:
        without_cohort = replace(
            self.proposal,
            evidence_record_ids=tuple(
                value
                for value in self.proposal.evidence_record_ids
                if value != self.cohort.record_id
            ),
        )
        unknown_baseline = replace(
            self.proposal,
            baseline_local_dates=("2030-01-01",),
        )
        interval = self.proposal.representative_intervals[0]
        unknown_interval = replace(
            interval,
            night_record_id="night:unknown",
            session_record_id="session:unknown",
            source_record_ids=(
                "night:unknown",
                "session:unknown",
                interval.source_record_ids[2],
            ),
        )
        interval_proposal = replace(
            self.proposal,
            evidence_record_ids=(
                *self.proposal.evidence_record_ids,
                "night:unknown",
                "session:unknown",
            ),
            representative_intervals=(unknown_interval,),
        )
        cases = (
            ("link the selected cohort", without_cohort),
            ("baseline date", unknown_baseline),
            ("resolve to its selected cohort", interval_proposal),
        )
        for message, proposal in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                RetrospectiveProtocolError,
                message,
            ):
                with ExperimentStore(self.database_path) as store:
                    record_retrospective_protocol(
                        store,
                        self.fixture.experiment.record_id,
                        self.cohort,
                        self._protocol(proposal),
                    )

    def test_second_protocol_is_refused_without_changing_history(self) -> None:
        with ExperimentStore(self.database_path) as store:
            first = record_retrospective_protocol(
                store,
                self.fixture.experiment.record_id,
                self.cohort,
                self.protocol,
            )
            with self.assertRaisesRegex(
                RetrospectiveProtocolError,
                "already contains",
            ):
                record_retrospective_protocol(
                    store,
                    self.fixture.experiment.record_id,
                    self.cohort,
                    self.protocol,
                )
            self.assertEqual(
                store.replay(self.fixture.experiment.record_id),
                first,
            )

    def test_batch_failure_preserves_every_prior_event(self) -> None:
        with ExperimentStore(self.database_path) as store:
            initial = store.replay(self.fixture.experiment.record_id)
            built = build_retrospective_protocol_events(
                initial,
                self.cohort,
                self.protocol,
            )
            collision = ExperimentEvent(
                record_id=built[-1].record_id,
                experiment_record_id=self.fixture.experiment.record_id,
                sequence_number=3,
                event_type=ExperimentEventType.NOTE_RECORDED,
                recorded_at_ms=self.protocol.proposal_recorded_at_ms - 1,
                recorded_by="user:local",
                payload=NoteRecordedPayload(
                    "Synthetic identifier collision",
                    self.fixture.history[0].record_id,
                ),
                source_class=SourceClass.USER_REPORTED,
                source_record_ids=(self.fixture.experiment.record_id,),
                source_provenance_ids=("provenance:user:synthetic",),
            )
            store.append_event(collision)
            before = store.replay(self.fixture.experiment.record_id)

            with self.assertRaises(ExperimentStoreError):
                record_retrospective_protocol(
                    store,
                    self.fixture.experiment.record_id,
                    self.cohort,
                    self.protocol,
                )

            self.assertEqual(
                store.replay(self.fixture.experiment.record_id),
                before,
            )
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM experiment_events").fetchone()[0],
                3,
            )

    def test_protocol_input_and_cohort_evidence_are_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.protocol.recorded_by = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            self.cohort.record_id = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
