"""Focused tests for the safe PS Min retrospective reconstruction fixture."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from pap_pilot.engine import (
    LOCAL_EXPERIMENT_DATABASE_FILENAME,
    PS_MIN_RETROSPECTIVE_FIXTURE_ENGINE_VERSION,
    PS_MIN_RETROSPECTIVE_FIXTURE_ID,
    PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION,
    PS_MIN_RETROSPECTIVE_FIXTURE_VERSION,
    ExperimentEventType,
    ExperimentStore,
    RetrospectiveFixtureEvaluationStatus,
    RetrospectiveMissingInputId,
    reconstruct_ps_min_experiment_fixture,
)


class PSMinRetrospectiveFixtureTests(unittest.TestCase):
    """Verify replay, evidence linkage, missing inputs, and non-fabrication."""

    def test_fixture_identity_and_known_change_are_exact(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()

        self.assertEqual(
            (fixture.fixture_id, fixture.fixture_version, fixture.record_version),
            (PS_MIN_RETROSPECTIVE_FIXTURE_ID, PS_MIN_RETROSPECTIVE_FIXTURE_VERSION, PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION),
        )
        self.assertEqual(PS_MIN_RETROSPECTIVE_FIXTURE_ENGINE_VERSION, "0.1.0")
        self.assertEqual((fixture.known_change.previous.name, fixture.known_change.previous.value, fixture.known_change.proposed.value, fixture.known_change.previous.unit), ("ps_min", 2.0, 1.0, "cm H₂O"))
        self.assertEqual(tuple(value.record_id for value in fixture.known_facts), ("fact:analysis-contract", "fact:informal-impression", "fact:ps-min-change"))

    def test_partial_history_replays_through_the_append_only_store(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()
        self.assertEqual(tuple(value.event_type for value in fixture.history), (ExperimentEventType.PROBLEM_RECORDED, ExperimentEventType.HYPOTHESIS_DRAFTED))

        with TemporaryDirectory() as directory:
            database_path = Path(directory) / LOCAL_EXPERIMENT_DATABASE_FILENAME
            with ExperimentStore(database_path) as store:
                store.create_experiment(fixture.experiment)
                for event in fixture.history:
                    store.append_event(event)
                first_replay = store.replay(fixture.experiment.record_id)
            with ExperimentStore(database_path) as reopened:
                second_replay = reopened.replay(fixture.experiment.record_id)

        self.assertEqual(first_replay, second_replay)
        self.assertEqual(first_replay.experiment, fixture.experiment)
        self.assertEqual(first_replay.history, fixture.history)
        self.assertEqual(first_replay.effective_events, fixture.history)
        self.assertEqual(first_replay.journal_history, ())

    def test_every_missing_retrospective_input_is_explicit(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()
        expected = set(RetrospectiveMissingInputId)

        self.assertEqual({value.input_id for value in fixture.missing_inputs}, expected)
        self.assertEqual(set(fixture.evaluation.missing_input_ids), expected)
        self.assertTrue(all(value.description and value.blocks and value.source_record_ids for value in fixture.missing_inputs))
        self.assertEqual(
            fixture.evaluation.reason_codes,
            (
                "accepted_proposal_missing",
                "applied_change_boundary_missing",
                "baseline_intervention_nights_missing",
                "confounder_adverse_effect_evidence_missing",
                "objective_metric_results_missing",
                "outcome_classification_not_issued",
                "quality_reports_missing",
                "representative_intervals_missing",
                "structured_journal_reports_missing",
            ),
        )

    def test_missing_evidence_is_not_replaced_with_retrospective_observations(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()

        self.assertEqual(fixture.normalized_nights, ())
        self.assertEqual(fixture.structural_quality_reports, ())
        self.assertEqual(fixture.signal_quality_reports, ())
        self.assertIsNone(fixture.allocation)
        self.assertEqual(fixture.metric_results, ())
        self.assertEqual(fixture.journal_entries, ())
        self.assertEqual(fixture.evidence_events, ())
        self.assertIsNone(fixture.outcome_classification)
        self.assertNotIn(ExperimentEventType.EXPERIMENT_PROPOSED, {value.event_type for value in fixture.history})
        self.assertNotIn(ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED, {value.event_type for value in fixture.history})

    def test_readiness_evaluation_is_deterministic_and_does_not_claim_a_classification(self) -> None:
        first = reconstruct_ps_min_experiment_fixture()
        second = reconstruct_ps_min_experiment_fixture()

        self.assertEqual(first, second)
        self.assertEqual(first.evaluation, second.evaluation)
        self.assertEqual(first.evaluation.record_id, "retrospective-fixture-evaluation:9d6a7017cc7b683ae248")
        self.assertIs(first.evaluation.status, RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION)
        self.assertIsNone(first.evaluation.outcome_classification_record_id)

    def test_every_claim_and_evaluation_reference_is_linked_to_the_source_inventory(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()
        inventory = set(fixture.source_record_ids)
        repository_root = Path(__file__).parents[1]

        for item in (*fixture.known_facts, *fixture.missing_inputs):
            self.assertLessEqual(set(item.source_record_ids), inventory)
            for source_record_id in item.source_record_ids:
                self.assertTrue((repository_root / source_record_id.split("#", 1)[0]).is_file())
        self.assertLessEqual(set(fixture.evaluation.source_record_ids), inventory)
        for event in fixture.history:
            self.assertIn(fixture.experiment.record_id, event.source_record_ids)
            self.assertLessEqual(set(event.source_record_ids), inventory)

    def test_fixture_retains_no_private_date_or_source_identity(self) -> None:
        fixture_text = repr(reconstruct_ps_min_experiment_fixture())

        self.assertIsNone(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", fixture_text))
        self.assertNotIn("profile:", fixture_text)
        self.assertNotIn("machine:", fixture_text)
        self.assertNotIn("session:", fixture_text)

    def test_records_and_collections_are_immutable(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()

        with self.assertRaises(FrozenInstanceError):
            fixture.record_id = "replacement"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            fixture.evaluation.status = RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION  # type: ignore[misc]
        self.assertIs(type(fixture.history), tuple)
        self.assertIs(type(fixture.missing_inputs), tuple)


if __name__ == "__main__":
    unittest.main()
