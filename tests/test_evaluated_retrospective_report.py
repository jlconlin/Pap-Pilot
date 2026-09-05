"""Focused S37E tests for evaluated retrospective reports and excerpts."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pap_pilot.engine import (
    EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
    EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
    EvidenceAvailability,
    ExperimentPeriod,
    ExperimentStore,
    OutcomeAction,
    OutcomeClassification,
    RetrospectiveEvidenceReportError,
    RetrospectiveEvidenceReportStatus,
    RetrospectiveEvidenceStatus,
    RetrospectiveMissingInputId,
    RetrospectiveRepresentativeIntervalSelection,
    build_evaluated_retrospective_evidence_report,
    reconstruct_ps_min_experiment_fixture,
    record_retrospective_protocol,
    record_retrospective_user_evidence,
    serialize_retrospective_evidence_report,
)
from pap_pilot.workflow import evaluate_selected_oscar_retrospective_experiment
from tests.test_retrospective_evaluation import (
    _cohort,
    _generic_cohort,
    _journal_inputs,
    _proposal,
    _protocol,
)


_EXPECTED_PATH = Path(__file__).parent / "fixtures" / "evaluated-retrospective-evidence-report-v2.json"


class EvaluatedRetrospectiveEvidenceReportTests(unittest.TestCase):
    """Verify populated, missing, bounded, linked, and stable report states."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.oscar_cohort = _cohort()
        self.cohort = _generic_cohort(self.oscar_cohort)
        self.evaluation = self._evaluate(_journal_inputs(self.cohort), "complete")
        self.selections = self._selections(("flow_rate", "mask_pressure", "leak_rate"))

    def test_populated_report_covers_every_required_section(self) -> None:
        report = build_evaluated_retrospective_evidence_report(self.evaluation, self.selections)

        self.assertEqual(
            (report.schema_version, report.record_version, report.evaluation_status),
            (
                EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
                EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
                RetrospectiveEvidenceReportStatus.EVALUATED,
            ),
        )
        self.assertEqual(report.cohort_record_id, self.evaluation.cohort_record_id)
        self.assertEqual(tuple(value.night_count for value in report.periods), (3, 3))
        self.assertTrue(all(value.availability is EvidenceAvailability.AVAILABLE for value in report.periods))
        self.assertTrue(all(value.availability is EvidenceAvailability.AVAILABLE for value in (*report.objective_metrics, *report.subjective_outcomes)))
        self.assertTrue(all(value.outcome_state is not None for value in (*report.objective_metrics, *report.subjective_outcomes)))
        self.assertIs(report.quality_evidence.availability, EvidenceAvailability.AVAILABLE)
        self.assertIs(report.confounder_evidence.availability, EvidenceAvailability.AVAILABLE)
        self.assertIs(report.adverse_effect_evidence.availability, EvidenceAvailability.AVAILABLE)
        self.assertEqual(report.missing_inputs, ())
        self.assertIs(report.classification.availability, EvidenceAvailability.ISSUED)
        self.assertEqual(
            (report.classification.classification, report.classification.action),
            (OutcomeClassification.CLEAR_IMPROVEMENT.value, OutcomeAction.KEEP.value),
        )
        self.assertTrue(report.limitations)
        self.assertTrue(report.uncertainty)

    def test_both_selected_intervals_retain_exact_bounded_samples_and_links(self) -> None:
        report = build_evaluated_retrospective_evidence_report(self.evaluation, self.selections)
        inventory = set(report.provenance.source_record_ids)

        self.assertEqual(tuple(value.period for value in report.representative_intervals), tuple(ExperimentPeriod))
        for interval, expected_pressure in zip(report.representative_intervals, (13.0, 12.5)):
            self.assertEqual(interval.end_ms - interval.start_ms, 200)
            self.assertEqual(tuple(value.signal_kind for value in interval.signals), ("flow_rate", "mask_pressure", "leak"))
            flow, pressure, leak = interval.signals
            self.assertEqual((flow.availability, pressure.availability, leak.availability), (EvidenceAvailability.AVAILABLE, EvidenceAvailability.AVAILABLE, EvidenceAvailability.MISSING))
            self.assertEqual((len(flow.values), set(flow.values)), (5, {10.0}))
            self.assertEqual((len(pressure.values), set(pressure.values)), (5, {expected_pressure}))
            self.assertEqual((leak.signal_record_id, leak.sample_times_ms, leak.values), (None, (), ()))
            self.assertIn("bounded_signal_samples_unavailable", leak.reason_codes)
            self.assertTrue(set(interval.source_record_ids).issubset(inventory))
            self.assertTrue(all(set(value.source_record_ids).issubset(inventory) for value in interval.signals))

    def test_missing_subjective_evidence_remains_explicit_in_an_issued_inconclusive_report(self) -> None:
        inputs = tuple(
            replace(value, journal_status=RetrospectiveEvidenceStatus.UNAVAILABLE, journal_entry=None)
            for value in _journal_inputs(self.cohort)
        )
        evaluation = self._evaluate(inputs, "status-only")
        report = build_evaluated_retrospective_evidence_report(evaluation, self.selections)

        self.assertTrue(all(value.availability is EvidenceAvailability.MISSING for value in report.subjective_outcomes))
        self.assertTrue(all(value.outcome_state == "insufficient_evidence" for value in report.subjective_outcomes))
        self.assertEqual(tuple(value.input_id for value in report.missing_inputs), (RetrospectiveMissingInputId.STRUCTURED_JOURNAL_REPORTS,))
        self.assertEqual(
            (report.classification.availability, report.classification.classification, report.classification.action),
            (EvidenceAvailability.ISSUED, OutcomeClassification.INCONCLUSIVE.value, OutcomeAction.EXTEND.value),
        )
        self.assertIn("subjective_anchor_missing", report.classification.reason_codes)

    def test_selection_contract_refuses_automatic_or_unbounded_substitutes(self) -> None:
        with self.assertRaisesRegex(RetrospectiveEvidenceReportError, "no longer than 60,000"):
            replace(self.selections[0], end_ms=self.selections[0].start_ms + 60_001)
        with self.assertRaisesRegex(RetrospectiveEvidenceReportError, "only Flow Rate"):
            replace(self.selections[0], signal_kinds=("tidal_volume",))
        with self.assertRaisesRegex(RetrospectiveEvidenceReportError, "cover baseline and intervention"):
            build_evaluated_retrospective_evidence_report(self.evaluation, tuple(reversed(self.selections)))
        with self.assertRaisesRegex(RetrospectiveEvidenceReportError, "inside one eligible allocation interval"):
            outside = replace(self.selections[0], start_ms=self.selections[0].start_ms - 200, end_ms=self.selections[0].start_ms)
            build_evaluated_retrospective_evidence_report(self.evaluation, (outside, self.selections[1]))

    def test_serialization_and_review_snapshot_are_stable(self) -> None:
        report = build_evaluated_retrospective_evidence_report(self.evaluation, self.selections)
        compact = serialize_retrospective_evidence_report(report)
        observed = {
            "canonical_sha256": hashlib.sha256(compact.encode()).hexdigest(),
            "classification": report.classification.classification,
            "classification_action": report.classification.action,
            "confounder_availability": report.confounder_evidence.availability.value,
            "evaluation_record_id": report.evaluation_record_id,
            "evaluation_status": report.evaluation_status.value,
            "intervals": [
                {
                    "available_sample_counts": [len(signal.values) for signal in interval.signals if signal.availability is EvidenceAvailability.AVAILABLE],
                    "duration_ms": interval.end_ms - interval.start_ms,
                    "period": interval.period.value,
                    "signal_availability": {signal.signal_kind: signal.availability.value for signal in interval.signals},
                }
                for interval in report.representative_intervals
            ],
            "missing_input_ids": [value.input_id.value for value in report.missing_inputs],
            "objective_outcomes": [
                {
                    "baseline_median": value.baseline.median,
                    "change": value.intervention_minus_baseline,
                    "intervention_median": value.intervention.median,
                    "outcome_id": value.outcome_id.value,
                    "state": value.outcome_state,
                }
                for value in report.objective_metrics
            ],
            "period_night_counts": {value.period.value: value.night_count for value in report.periods},
            "quality_record_count": report.quality_evidence.record_count,
            "record_id": report.record_id,
            "record_version": report.record_version,
            "schema_version": report.schema_version,
            "subjective_outcomes": [
                {
                    "baseline_median": value.baseline.median,
                    "change": value.intervention_minus_baseline,
                    "intervention_median": value.intervention.median,
                    "outcome_id": value.outcome_id.value,
                    "state": value.outcome_state,
                }
                for value in report.subjective_outcomes
            ],
        }

        self.assertEqual(observed, json.loads(_EXPECTED_PATH.read_text(encoding="utf-8")))
        self.assertEqual(compact, serialize_retrospective_evidence_report(build_evaluated_retrospective_evidence_report(self.evaluation, self.selections)))
        self.assertNotIn("\n", compact)

    def test_report_and_selection_are_deeply_immutable(self) -> None:
        report = build_evaluated_retrospective_evidence_report(self.evaluation, self.selections)

        with self.assertRaises(FrozenInstanceError):
            report.cohort_record_id = "cohort:replacement"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            report.representative_intervals[0].signals[0].values = ()  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            self.selections[0].end_ms = self.selections[0].start_ms  # type: ignore[misc]

    def _evaluate(self, inputs, suffix):
        fixture = reconstruct_ps_min_experiment_fixture()
        database_path = Path(self.temporary_directory.name) / suffix / "pap_pilot.sqlite3"
        database_path.parent.mkdir()
        with ExperimentStore(database_path) as store:
            store.create_experiment(fixture.experiment)
            store.append_events(fixture.history)
            record_retrospective_protocol(
                store,
                fixture.experiment.record_id,
                self.cohort,
                _protocol(fixture, _proposal(fixture, self.cohort)),
            )
            replayed = record_retrospective_user_evidence(
                store,
                fixture.experiment.record_id,
                self.cohort,
                inputs,
            )
        return evaluate_selected_oscar_retrospective_experiment(self.oscar_cohort, replayed)

    def _selections(self, signal_kinds):
        values = []
        for period, index in ((ExperimentPeriod.BASELINE, 0), (ExperimentPeriod.INTERVENTION, 3)):
            night = self.cohort.nights[index]
            session = night.sessions[0]
            values.append(
                RetrospectiveRepresentativeIntervalSelection(
                    record_id=f"selection:{period.value}",
                    period=period,
                    night_record_id=night.record_id,
                    session_record_id=session.record_id,
                    start_ms=session.start_time_ms,
                    end_ms=session.start_time_ms + 200,
                    signal_kinds=signal_kinds,
                )
            )
        return tuple(values)


if __name__ == "__main__":
    unittest.main()
