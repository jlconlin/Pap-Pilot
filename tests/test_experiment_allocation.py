"""Focused tests for deterministic experiment-night allocation."""

from dataclasses import FrozenInstanceError
import unittest

from pap_pilot.engine import (
    EXPERIMENT_ALLOCATION_RULE_SET_ID,
    EXPERIMENT_ALLOCATION_RULE_SET_VERSION,
    ExperimentAllocationError,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentPeriod,
    ExperimentSetting,
    ExperimentSettingChange,
    IntervalClosure,
    NightAllocationStatus,
    NightRecord,
    ProblemRecordedPayload,
    ProvenanceRecord,
    QualityFinding,
    QualityImpact,
    QualityRule,
    QualityStatus,
    QualityValue,
    SessionRecord,
    SettingChangeConfirmedPayload,
    SignalQualityReport,
    SignalRecord,
    SignalRepresentation,
    SignalSegmentRecord,
    SourceClass,
    SourceReference,
    allocate_experiment_nights,
    evaluate_structural_quality,
)


class ExperimentAllocationTests(unittest.TestCase):
    """Verify exact boundary membership and quality-directed exclusions."""

    def setUp(self) -> None:
        self.change = ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 1.0, "cm H₂O"))

    def test_exact_boundary_assigns_preceding_and_following_nights(self) -> None:
        baseline = self._night("2026-08-30", 0, 500_000)
        intervention = self._night("2026-08-31", 500_000, 1_000_000)
        result = allocate_experiment_nights(
            (intervention, baseline),
            self._change_event(500_000),
            (self._report(intervention), self._report(baseline)),
        )

        self.assertEqual(tuple(value.local_date for value in result.nights), ("2026-08-30", "2026-08-31"))
        self.assertEqual(result.included(ExperimentPeriod.BASELINE), (result.nights[0],))
        self.assertEqual(result.included(ExperimentPeriod.INTERVENTION), (result.nights[1],))
        self.assertEqual(result.excluded, ())
        self.assertEqual(result.nights[0].eligible_intervals[0].end_time_ms, 500_000)
        self.assertEqual(result.nights[1].eligible_intervals[0].start_time_ms, 500_000)
        self.assertEqual((result.rule_set_id, result.rule_set_version), (EXPERIMENT_ALLOCATION_RULE_SET_ID, EXPERIMENT_ALLOCATION_RULE_SET_VERSION))

    def test_night_crossing_confirmed_boundary_is_excluded_from_both_periods(self) -> None:
        crossing = self._night("2026-08-31", 400_000, 600_000)

        result = allocate_experiment_nights((crossing,), self._change_event(500_000), (self._report(crossing),))
        allocation = result.nights[0]

        self.assertIsNone(allocation.period)
        self.assertEqual(allocation.status, NightAllocationStatus.EXCLUDED)
        self.assertEqual(allocation.exclusion_reason_codes, ("change_boundary_overlap",))
        self.assertEqual(allocation.eligible_intervals, ())
        self.assertEqual(allocation.excluded_intervals, allocation.requested_intervals)

    def test_interval_quality_exclusion_preserves_usable_period_membership(self) -> None:
        night = self._night("2026-08-30", 0, 500_000, flow_coverage=((0, 100_000), (200_000, 500_000)))
        report = evaluate_structural_quality(night, required_signal_kinds=("flow_rate",))

        result = allocate_experiment_nights((night,), self._change_event(600_000), (report,))
        allocation = result.nights[0]

        self.assertEqual((allocation.period, allocation.status), (ExperimentPeriod.BASELINE, NightAllocationStatus.INCLUDED))
        self.assertEqual(tuple((value.start_time_ms, value.end_time_ms) for value in allocation.excluded_intervals), ((100_000, 200_000),))
        self.assertEqual(tuple((value.start_time_ms, value.end_time_ms) for value in allocation.eligible_intervals), ((0, 100_000), (200_000, 500_000)))
        self.assertEqual(allocation.excluded_intervals[0].reason_codes, ("coverage_gap",))
        self.assertFalse(allocation.exclusion_reason_codes)

    def test_blocking_quality_finding_excludes_the_assigned_night(self) -> None:
        night = self._night("2026-08-31", 500_000, 1_000_000)
        blocking_report = evaluate_structural_quality(night, required_signal_kinds=("flow_rate",))

        result = allocate_experiment_nights((night,), self._change_event(500_000), (blocking_report,))
        allocation = result.nights[0]

        self.assertEqual(allocation.period, ExperimentPeriod.INTERVENTION)
        self.assertEqual(allocation.status, NightAllocationStatus.EXCLUDED)
        self.assertIn("quality_block_requested_analysis", allocation.exclusion_reason_codes)
        self.assertIn("channel_missing", allocation.exclusion_reason_codes)
        self.assertEqual(allocation.eligible_intervals, ())
        self.assertTrue(allocation.excluded_intervals[0].quality_finding_ids)

    def test_signal_quality_interval_is_applied_without_excluding_the_night(self) -> None:
        night = self._night("2026-08-30", 0, 500_000)
        session = night.sessions[0]
        finding = QualityFinding(
            record_id="quality:large-leak",
            rule_id=QualityRule.LARGE_LEAK,
            status=QualityStatus.FLAGGED,
            impact=QualityImpact.EXCLUDE_INTERVAL,
            reason_code="threshold_exceeded",
            evaluated_record_id=session.record_id,
            source_record_ids=(session.record_id,),
            source_provenance_ids=(session.provenance.record_id,),
            parameters=(QualityValue("large_leak_threshold_l_min", 24.0, "L/min"),),
            measurements=(QualityValue("maximum_leak_l_min", 30.0, "L/min"),),
            limitations=("Synthetic quality evidence for allocation testing.",),
            affected_capabilities=("pressure_response",),
            start_time_ms=100_000,
            end_time_ms=200_000,
        )
        signal_report = SignalQualityReport(
            record_id="signal-quality:one",
            session_record_id=session.record_id,
            breath_series_record_id=None,
            findings=(finding,),
        )

        result = allocate_experiment_nights((night,), self._change_event(600_000), (self._report(night),), (signal_report,))
        allocation = result.nights[0]

        self.assertEqual(allocation.status, NightAllocationStatus.INCLUDED)
        self.assertEqual(allocation.signal_quality_report_ids, (signal_report.record_id,))
        self.assertEqual(allocation.excluded_intervals[0].quality_finding_ids, (finding.record_id,))
        self.assertEqual(tuple((value.start_time_ms, value.end_time_ms) for value in allocation.eligible_intervals), ((0, 100_000), (200_000, 500_000)))

    def test_existing_cautions_remain_visible_without_excluding_a_night(self) -> None:
        short_night = self._night("2026-08-30", 0, 299_999)

        result = allocate_experiment_nights((short_night,), self._change_event(400_000), (self._report(short_night),))
        allocation = result.nights[0]

        self.assertEqual(allocation.status, NightAllocationStatus.INCLUDED)
        self.assertTrue(allocation.caution_finding_ids)
        self.assertEqual(allocation.excluded_intervals, ())

    def test_allocation_requires_explicit_change_and_complete_matching_quality_reports(self) -> None:
        night = self._night("2026-08-30", 0, 500_000)
        following = self._night("2026-08-31", 500_000, 1_000_000)
        wrong_event = ExperimentEvent(
            record_id="event:problem",
            experiment_record_id="experiment:one",
            sequence_number=1,
            event_type=ExperimentEventType.PROBLEM_RECORDED,
            recorded_at_ms=1,
            recorded_by="user:local",
            payload=ProblemRecordedPayload("Problem"),
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=("experiment:one",),
            source_provenance_ids=("provenance:user",),
        )

        with self.assertRaisesRegex(ExperimentAllocationError, "setting-change-confirmed"):
            allocate_experiment_nights((night,), wrong_event, (self._report(night),))
        with self.assertRaisesRegex(ExperimentAllocationError, "Exactly one"):
            allocate_experiment_nights((night,), self._change_event(600_000), ())
        with self.assertRaisesRegex(ExperimentAllocationError, "same structural quality request"):
            allocate_experiment_nights(
                (night, following),
                self._change_event(500_000),
                (self._report(night), evaluate_structural_quality(following, required_signal_kinds=("flow_rate",))),
            )

    def test_result_is_deterministic_and_immutable(self) -> None:
        night = self._night("2026-08-30", 0, 500_000)
        arguments = ((night,), self._change_event(600_000), (self._report(night),))

        first = allocate_experiment_nights(*arguments)
        second = allocate_experiment_nights(*arguments)

        self.assertEqual(first, second)
        with self.assertRaises(FrozenInstanceError):
            first.applied_at_ms = 1  # type: ignore[misc]

    def _change_event(self, applied_at_ms: int) -> ExperimentEvent:
        return ExperimentEvent(
            record_id="event:change-confirmed",
            experiment_record_id="experiment:one",
            sequence_number=1,
            event_type=ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED,
            recorded_at_ms=applied_at_ms + 1,
            recorded_by="user:local",
            payload=SettingChangeConfirmedPayload("event:accepted", self.change, applied_at_ms),
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=("experiment:one",),
            source_provenance_ids=("provenance:user",),
        )

    def _night(self, local_date: str, start: int, end: int, *, flow_coverage: tuple[tuple[int, int], ...] = ()) -> NightRecord:
        suffix = local_date
        provenance = ProvenanceRecord(
            record_id=f"provenance:{suffix}",
            source_classes=(SourceClass.MACHINE_RECORDED, SourceClass.OSCAR_NORMALIZED),
            source_system="synthetic",
            source_references=(SourceReference("session", f"source:{suffix}"),),
        )
        segments = tuple(
            SignalSegmentRecord(
                record_id=f"segment:{suffix}:{index}",
                start_time_ms=segment_start,
                end_time_ms=segment_end,
                interval_closure=IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                sample_times_ms=(float(segment_start), float((segment_start + segment_end) / 2)),
                values=(1.0, 1.0),
                sample_interval_ms=(segment_end - segment_start) / 2,
                provenance=provenance,
            )
            for index, (segment_start, segment_end) in enumerate(flow_coverage)
        )
        signals = () if not segments else (
            SignalRecord(
                record_id=f"signal:flow:{suffix}",
                signal_kind="flow_rate",
                unit="L/min",
                representation=SignalRepresentation.UNIFORM_WAVEFORM,
                segments=segments,
                provenance=provenance,
            ),
        )
        session = SessionRecord(
            record_id=f"session:{suffix}",
            device_id="device:synthetic",
            start_time_ms=start,
            end_time_ms=end,
            settings=(),
            events=(),
            signals=signals,
            provenance=provenance,
        )
        return NightRecord(
            record_id=f"night:{suffix}",
            local_date=local_date,
            timezone="America/Denver",
            day_boundary_local_time="12:00:00",
            sessions=(session,),
            provenance=provenance,
        )

    @staticmethod
    def _report(night: NightRecord):
        return evaluate_structural_quality(night)


if __name__ == "__main__":
    unittest.main()
