"""Focused tests for the deterministic S32 retrospective evidence report."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import re
import unittest

from pap_pilot.engine import (
    RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION,
    RETROSPECTIVE_EVIDENCE_REPORT_FORMAT,
    RETROSPECTIVE_EVIDENCE_REPORT_FORMAT_VERSION,
    RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
    RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID,
    RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
    EvidenceAvailability,
    ExperimentPeriod,
    OutcomeId,
    RetrospectiveFixtureEvaluationStatus,
    RetrospectiveMissingInputId,
    build_ps_min_retrospective_evidence_report,
    reconstruct_ps_min_experiment_fixture,
    serialize_retrospective_evidence_report,
)


class RetrospectiveEvidenceReportTests(unittest.TestCase):
    """Verify stable output, evidence linkage, and explicit unknowns."""

    def test_report_identity_and_versions_are_exact(self) -> None:
        report = build_ps_min_retrospective_evidence_report()

        self.assertEqual(report.record_id, "retrospective-evidence-report:9fea573d7f88ea9206c0")
        self.assertEqual(
            (report.schema_id, report.schema_version, report.record_version, report.engine_version),
            (
                RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID,
                RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
                RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
                RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION,
            ),
        )
        self.assertIs(report.evaluation_status, RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION)
        self.assertEqual((report.known_change.setting_name, report.known_change.baseline_value, report.known_change.intervention_value, report.known_change.unit), ("ps_min", 2.0, 1.0, "cm H₂O"))

    def test_report_contains_every_required_section_without_inventing_values(self) -> None:
        report = build_ps_min_retrospective_evidence_report()

        self.assertEqual(tuple(value.period for value in report.periods), (ExperimentPeriod.BASELINE, ExperimentPeriod.INTERVENTION))
        self.assertEqual(tuple(value.outcome_id for value in report.objective_metrics), (OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP, OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO))
        self.assertEqual(tuple(value.outcome_id for value in report.subjective_outcomes), (OutcomeId.AWAKENINGS_COUNT, OutcomeId.SLEEP_QUALITY, OutcomeId.MORNING_ENERGY, OutcomeId.DAYTIME_TIREDNESS))
        self.assertEqual(tuple(value.period for value in report.representative_intervals), (ExperimentPeriod.BASELINE, ExperimentPeriod.INTERVENTION))
        self.assertEqual({value.input_id for value in report.missing_inputs}, set(RetrospectiveMissingInputId))
        self.assertTrue(all(value.availability is EvidenceAvailability.MISSING and value.night_count == 0 and not value.night_record_ids for value in report.periods))
        self.assertTrue(all(value.availability is EvidenceAvailability.MISSING and value.record_count == 0 and not value.record_ids for value in (report.quality_evidence, report.confounder_evidence, report.adverse_effect_evidence)))
        self.assertTrue(all(value.availability is EvidenceAvailability.MISSING and value.interval_record_id is None and value.start_ms is None and value.end_ms is None for value in report.representative_intervals))

    def test_outcome_contracts_are_visible_but_results_remain_unknown(self) -> None:
        report = build_ps_min_retrospective_evidence_report()
        outcomes = (*report.objective_metrics, *report.subjective_outcomes)

        self.assertEqual(tuple(value.unit for value in report.objective_metrics), ("cm H₂O", "1"))
        self.assertEqual(tuple(value.prespecified_threshold for value in outcomes), (0.5, 0.1, 1.0, 1.0, 1.0, 1.0))
        for outcome in outcomes:
            self.assertIs(outcome.availability, EvidenceAvailability.MISSING)
            self.assertIsNone(outcome.intervention_minus_baseline)
            self.assertIsNone(outcome.outcome_state)
            for arm in (outcome.baseline, outcome.intervention):
                self.assertEqual(arm.count, 0)
                self.assertEqual((arm.minimum, arm.median, arm.maximum, arm.median_absolute_deviation), (None, None, None, None))
                self.assertEqual(arm.evidence_record_ids, ())

    def test_no_classification_or_action_is_issued(self) -> None:
        report = build_ps_min_retrospective_evidence_report()

        self.assertIs(report.classification.availability, EvidenceAvailability.NOT_ISSUED)
        self.assertIsNone(report.classification.classification_record_id)
        self.assertIsNone(report.classification.classification)
        self.assertIsNone(report.classification.action)
        self.assertIn("outcome_classification_not_issued", report.classification.reason_codes)
        self.assertIn("Absence of retained observations means unknown, not zero, unchanged, favorable, or safe.", report.uncertainty)

    def test_report_is_traceable_to_fixture_and_repository_sources(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()
        report = build_ps_min_retrospective_evidence_report(fixture)
        inventory = set(report.provenance.source_record_ids)
        repository_root = Path(__file__).parents[1]

        self.assertEqual(report.fixture_record_id, fixture.record_id)
        self.assertEqual(report.experiment_record_id, fixture.experiment.record_id)
        self.assertEqual(report.evaluation_record_id, fixture.evaluation.record_id)
        self.assertEqual(tuple(value.record_id for value in report.history), tuple(value.record_id for value in fixture.history))
        self.assertEqual(tuple(value.record_id for value in report.known_facts), tuple(value.record_id for value in fixture.known_facts))
        self.assertIn(fixture.record_id, inventory)
        for source_record_id in inventory:
            if source_record_id.endswith(".md") or ".md#" in source_record_id:
                self.assertTrue((repository_root / source_record_id.split("#", 1)[0]).is_file())

    def test_serialization_is_canonical_and_snapshot_stable(self) -> None:
        report = build_ps_min_retrospective_evidence_report()
        compact = serialize_retrospective_evidence_report(report)
        pretty = serialize_retrospective_evidence_report(report, pretty=True)
        expected = (Path(__file__).parent / "fixtures" / "ps-min-retrospective-evidence-report-v1.json").read_text()

        self.assertEqual(pretty, expected)
        self.assertEqual(json.loads(compact), json.loads(pretty))
        self.assertEqual(compact, serialize_retrospective_evidence_report(build_ps_min_retrospective_evidence_report()))
        self.assertNotIn("\n", compact)
        self.assertEqual(json.loads(compact)["format"], RETROSPECTIVE_EVIDENCE_REPORT_FORMAT)
        self.assertEqual(json.loads(compact)["format_version"], RETROSPECTIVE_EVIDENCE_REPORT_FORMAT_VERSION)

    def test_report_retains_no_private_date_or_source_identity(self) -> None:
        report_text = serialize_retrospective_evidence_report(build_ps_min_retrospective_evidence_report(), pretty=True)

        self.assertIsNone(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", report_text))
        self.assertNotIn("profile:", report_text)
        self.assertNotIn("machine:", report_text)
        self.assertNotIn("session:", report_text)

    def test_report_and_nested_collections_are_immutable(self) -> None:
        report = build_ps_min_retrospective_evidence_report()

        with self.assertRaises(FrozenInstanceError):
            report.title = "replacement"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            report.objective_metrics[0].outcome_state = "favorable"  # type: ignore[misc]
        self.assertIs(type(report.periods), tuple)
        self.assertIs(type(report.missing_inputs), tuple)


if __name__ == "__main__":
    unittest.main()
