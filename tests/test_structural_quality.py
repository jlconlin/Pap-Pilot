"""Focused tests for version-1 structural quality findings."""

from dataclasses import FrozenInstanceError, replace
import unittest

from pap_pilot.engine.model import (
    IntervalClosure,
    NightRecord,
    ProvenanceRecord,
    ProvenanceValue,
    SessionRecord,
    SignalRecord,
    SignalRepresentation,
    SignalSegmentRecord,
    SourceClass,
    SourceReference,
)
from pap_pilot.engine.quality import (
    QUALITY_RULE_SET_ID,
    QUALITY_RULE_SET_VERSION,
    ClockCorrectionEvidence,
    ClockCorrectionEvidenceState,
    QualityImpact,
    QualityModelError,
    QualityRule,
    QualityStatus,
    TimeBasis,
    evaluate_clock_correction_integrity,
    evaluate_flow_pressure_alignment,
    evaluate_missing_required_signals,
    evaluate_short_session,
    evaluate_split_session_night,
    evaluate_structural_quality,
)


class StructuralQualityTests(unittest.TestCase):
    """Exercise pass, flag, insufficient-evidence, and exact-boundary behavior."""

    def setUp(self) -> None:
        self.provenance = _provenance("session")
        self.flow = _uniform_signal("flow_rate", "L/min", ((0, 600_000, 2),))
        self.pressure = _uniform_signal("mask_pressure", "cm H₂O", ((0, 600_000, 2),))
        self.leak = _timed_signal("leak_rate", "L/min", ((0, 600_000),))
        self.session = _session("session:1", 0, 600_000, (self.flow, self.pressure, self.leak), self.provenance)
        self.night = _night((self.session,))

    def test_missing_signal_passes_only_for_complete_supported_coverage(self) -> None:
        findings = evaluate_missing_required_signals(self.session, ("flow_rate", "mask_pressure", "leak_rate"))

        self.assertEqual(len(findings), 3)
        self.assertEqual({finding.status for finding in findings}, {QualityStatus.PASS})
        self.assertEqual({finding.impact for finding in findings}, {QualityImpact.NONE})
        self.assertEqual({finding.reason_code for finding in findings}, {"condition_not_observed"})

    def test_missing_signal_flags_every_exact_uncovered_interval(self) -> None:
        flow = _uniform_signal("flow_rate", "L/min", ((100_000, 500_000, 2),))
        session = replace(self.session, signals=(flow, self.pressure, self.leak))

        findings = evaluate_missing_required_signals(session, ("flow_rate",))

        self.assertEqual([(finding.start_time_ms, finding.end_time_ms) for finding in findings], [(0, 100_000), (500_000, 600_000)])
        self.assertEqual({finding.status for finding in findings}, {QualityStatus.FLAGGED})
        self.assertEqual({finding.reason_code for finding in findings}, {"coverage_gap"})
        self.assertEqual({finding.impact for finding in findings}, {QualityImpact.EXCLUDE_INTERVAL})

    def test_timed_update_final_value_is_not_held_to_the_segment_boundary(self) -> None:
        leak = _timed_signal("leak_rate", "L/min", ((0, 400_000),), segment_end=600_000)
        session = replace(self.session, signals=(self.flow, self.pressure, leak))

        finding = evaluate_missing_required_signals(session, ("leak_rate",))[0]

        self.assertEqual((finding.status, finding.reason_code), (QualityStatus.FLAGGED, "coverage_gap"))
        self.assertEqual((finding.start_time_ms, finding.end_time_ms), (400_000, 600_000))

    def test_absent_empty_and_unsupported_signals_are_insufficient(self) -> None:
        absent = replace(self.session, signals=(self.flow, self.pressure))
        empty = SignalRecord(
            record_id="signal:leak_rate:empty",
            signal_kind="leak_rate",
            unit="L/min",
            representation=SignalRepresentation.TIMED_UPDATES,
            segments=(),
            provenance=_provenance("leak-empty", availability="data_missing"),
        )
        empty_session = replace(self.session, signals=(self.flow, self.pressure, empty))
        unsupported = replace(self.flow, unit="mL/s")
        unsupported_session = replace(self.session, signals=(unsupported, self.pressure, self.leak))

        cases = (
            (absent, "leak_rate", "channel_missing"),
            (empty_session, "leak_rate", "data_missing"),
            (unsupported_session, "flow_rate", "unsupported_signal_contract"),
            (self.session, "unknown_signal", "unsupported_signal_contract"),
        )
        for session, signal_kind, reason in cases:
            with self.subTest(reason=reason):
                finding = evaluate_missing_required_signals(session, (signal_kind,))[0]
                self.assertEqual(finding.status, QualityStatus.INSUFFICIENT_EVIDENCE)
                self.assertEqual(finding.impact, QualityImpact.BLOCK_REQUESTED_ANALYSIS)
                self.assertEqual(finding.reason_code, reason)

    def test_disjoint_required_signal_coverage_has_no_common_eligible_interval(self) -> None:
        flow = _uniform_signal("flow_rate", "L/min", ((0, 300_000, 1),))
        pressure = _uniform_signal("mask_pressure", "cm H₂O", ((300_000, 600_000, 1),))
        session = replace(self.session, signals=(flow, pressure, self.leak))

        findings = evaluate_missing_required_signals(session, ("flow_rate", "mask_pressure"))

        common = [finding for finding in findings if finding.reason_code == "no_common_eligible_interval"]
        self.assertEqual(len(common), 1)
        self.assertEqual(common[0].status, QualityStatus.INSUFFICIENT_EVIDENCE)

    def test_no_required_signals_is_not_applicable(self) -> None:
        finding = evaluate_missing_required_signals(self.session, ())[0]

        self.assertEqual((finding.status, finding.reason_code, finding.impact), (QualityStatus.NOT_APPLICABLE, "rule_not_applicable", QualityImpact.NONE))

    def test_flow_pressure_alignment_passes_at_exact_equality(self) -> None:
        finding = evaluate_flow_pressure_alignment(self.session)

        self.assertEqual((finding.status, finding.reason_code, finding.impact), (QualityStatus.PASS, "condition_not_observed", QualityImpact.NONE))

    def test_flow_pressure_alignment_reports_each_mismatch_precedence(self) -> None:
        bounds_pressure = _uniform_signal("mask_pressure", "cm H₂O", ((0, 400_000, 2),))
        count_pressure = _uniform_signal("mask_pressure", "cm H₂O", ((0, 600_000, 3),))
        time_pressure = _uniform_signal("mask_pressure", "cm H₂O", ((0, 600_000, 2),), timestamp_adjustment=0.0000005)

        cases = (
            (bounds_pressure, "bounds_mismatch"),
            (count_pressure, "sample_count_mismatch"),
            (time_pressure, "sample_time_mismatch"),
        )
        for pressure, reason in cases:
            with self.subTest(reason=reason):
                session = replace(self.session, signals=(self.flow, pressure, self.leak))
                finding = evaluate_flow_pressure_alignment(session)
                self.assertEqual(finding.status, QualityStatus.FLAGGED)
                self.assertEqual(finding.impact, QualityImpact.EXCLUDE_INTERVAL)
                self.assertEqual(finding.reason_code, reason)

    def test_flow_pressure_alignment_is_insufficient_when_one_side_is_unavailable(self) -> None:
        session = replace(self.session, signals=(self.flow, self.leak))

        finding = evaluate_flow_pressure_alignment(session)

        self.assertEqual((finding.status, finding.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "paired_signal_unavailable"))

    def test_short_session_boundary_is_exactly_five_minutes(self) -> None:
        cases = (
            (299_999, QualityStatus.FLAGGED, "duration_below_300000_ms", QualityImpact.CAUTION),
            (300_000, QualityStatus.PASS, "condition_not_observed", QualityImpact.NONE),
            (300_001, QualityStatus.PASS, "condition_not_observed", QualityImpact.NONE),
        )
        for duration, status, reason, impact in cases:
            with self.subTest(duration=duration):
                session = _session(f"session:{duration}", 0, duration, (), self.provenance)
                finding = evaluate_short_session(session)
                self.assertEqual((finding.status, finding.reason_code, finding.impact), (status, reason, impact))

    def test_split_session_boundary_is_more_than_one_session(self) -> None:
        single = evaluate_split_session_night(self.night)
        second = _session("session:2", 700_000, 1_000_000, (), _provenance("session-2"))
        split = evaluate_split_session_night(_night((self.session, second)))

        self.assertEqual((single.status, single.reason_code), (QualityStatus.PASS, "condition_not_observed"))
        self.assertEqual((split.status, split.reason_code, split.impact), (QualityStatus.FLAGGED, "multiple_sessions", QualityImpact.CAUTION))
        measurements = {value.name: value.value for value in split.measurements}
        self.assertEqual(measurements["session_count"], 2)
        self.assertEqual(measurements["inter_session_gap_0_ms"], 100_000)

    def test_corrected_wall_clock_requires_explicit_correction_input(self) -> None:
        finding = evaluate_clock_correction_integrity(self.session)

        self.assertEqual((finding.status, finding.reason_code, finding.impact), (QualityStatus.INSUFFICIENT_EVIDENCE, "correction_input_missing", QualityImpact.BLOCK_REQUESTED_ANALYSIS))

    def test_confirmed_absence_of_clock_correction_passes(self) -> None:
        evidence = ClockCorrectionEvidence(ClockCorrectionEvidenceState.CONFIRMED_NONE, source_record_ids=("oscar:corrections-query",))

        finding = evaluate_clock_correction_integrity(self.session, evidence)

        self.assertEqual((finding.status, finding.reason_code), (QualityStatus.PASS, "condition_not_observed"))
        self.assertIn("oscar:corrections-query", finding.source_record_ids)

    def test_supported_constant_correction_is_flagged_and_kept_separate(self) -> None:
        evidence = ClockCorrectionEvidence(
            ClockCorrectionEvidenceState.SUPPORTED_CONSTANT,
            source_record_ids=("oscar:correction:1",),
            correction_types=("timezone",),
            total_offset_ms=3_600_000,
            corrected_start_time_ms=3_600_000,
            corrected_end_time_ms=4_200_000,
        )

        finding = evaluate_clock_correction_integrity(self.session, evidence)

        self.assertEqual((finding.status, finding.reason_code, finding.impact), (QualityStatus.FLAGGED, "supported_correction_present", QualityImpact.CAUTION))
        measurements = {value.name: value.value for value in finding.measurements}
        self.assertEqual(measurements["raw_start_time_ms"], 0)
        self.assertEqual(measurements["corrected_start_time_ms"], 3_600_000)
        self.assertEqual(self.session.start_time_ms, 0)

    def test_invalid_constant_correction_is_insufficient(self) -> None:
        evidence = ClockCorrectionEvidence(
            ClockCorrectionEvidenceState.SUPPORTED_CONSTANT,
            source_record_ids=("oscar:correction:1",),
            correction_types=("timezone",),
            total_offset_ms=3_600_000,
            corrected_start_time_ms=3_600_001,
            corrected_end_time_ms=4_200_001,
        )

        finding = evaluate_clock_correction_integrity(self.session, evidence)

        self.assertEqual((finding.status, finding.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "corrected_timeline_invalid"))

    def test_each_unresolved_correction_state_has_its_fixed_reason(self) -> None:
        cases = (
            (ClockCorrectionEvidenceState.RANGE_AMBIGUOUS, "correction_range_ambiguous"),
            (ClockCorrectionEvidenceState.UNSUPPORTED_DRIFT, "unsupported_drift"),
            (ClockCorrectionEvidenceState.STACKED_UNREPRODUCIBLE, "stacked_correction_unreproducible"),
        )
        for state, reason in cases:
            with self.subTest(state=state):
                evidence = ClockCorrectionEvidence(state, source_record_ids=(f"oscar:{state.value}",))
                finding = evaluate_clock_correction_integrity(self.session, evidence)
                self.assertEqual((finding.status, finding.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, reason))

    def test_queried_clock_state_requires_a_source_record(self) -> None:
        with self.assertRaises(QualityModelError):
            ClockCorrectionEvidence(ClockCorrectionEvidenceState.CONFIRMED_NONE)

    def test_raw_relative_work_passes_without_correction_evidence(self) -> None:
        finding = evaluate_clock_correction_integrity(self.session, time_basis=TimeBasis.RAW_RELATIVE)

        self.assertEqual((finding.status, finding.reason_code, finding.impact), (QualityStatus.PASS, "condition_not_observed", QualityImpact.NONE))

    def test_aggregate_report_is_deterministic_versioned_and_s19_only(self) -> None:
        report = evaluate_structural_quality(
            self.night,
            required_signal_kinds=("mask_pressure", "flow_rate"),
            require_flow_pressure_alignment=True,
            time_basis=TimeBasis.RAW_RELATIVE,
        )
        repeated = evaluate_structural_quality(
            self.night,
            required_signal_kinds=("flow_rate", "mask_pressure"),
            require_flow_pressure_alignment=True,
            time_basis=TimeBasis.RAW_RELATIVE,
        )

        self.assertEqual(report, repeated)
        self.assertEqual((report.rule_set_id, report.rule_set_version), (QUALITY_RULE_SET_ID, QUALITY_RULE_SET_VERSION))
        self.assertEqual(
            {finding.rule_id for finding in report.findings},
            {
                QualityRule.MISSING_REQUIRED_SIGNAL,
                QualityRule.FLOW_PRESSURE_MISALIGNMENT,
                QualityRule.SHORT_SESSION,
                QualityRule.SPLIT_SESSION_NIGHT,
                QualityRule.CLOCK_CORRECTION_INTEGRITY,
            },
        )
        self.assertEqual({finding.source_class for finding in report.findings}, {SourceClass.COMPANION_DERIVED})
        structural_rules = (
            QualityRule.SPLIT_SESSION_NIGHT,
            QualityRule.SHORT_SESSION,
            QualityRule.MISSING_REQUIRED_SIGNAL,
            QualityRule.FLOW_PRESSURE_MISALIGNMENT,
            QualityRule.CLOCK_CORRECTION_INTEGRITY,
        )
        rule_positions = {rule: min(index for index, finding in enumerate(report.findings) if finding.rule_id is rule) for rule in structural_rules}
        self.assertLess(rule_positions[QualityRule.MISSING_REQUIRED_SIGNAL], rule_positions[QualityRule.FLOW_PRESSURE_MISALIGNMENT])
        self.assertLess(rule_positions[QualityRule.FLOW_PRESSURE_MISALIGNMENT], rule_positions[QualityRule.CLOCK_CORRECTION_INTEGRITY])
        with self.assertRaises(FrozenInstanceError):
            report.night_record_id = "night:changed"  # type: ignore[misc]

    def test_aggregate_report_rejects_unknown_correction_session(self) -> None:
        with self.assertRaises(QualityModelError):
            evaluate_structural_quality(
                self.night,
                clock_corrections={
                    "session:unknown": ClockCorrectionEvidence(
                        ClockCorrectionEvidenceState.CONFIRMED_NONE,
                        source_record_ids=("oscar:corrections-query",),
                    )
                },
            )

    def test_aggregate_report_identity_includes_correction_evidence(self) -> None:
        without_input = evaluate_structural_quality(self.night, time_basis=TimeBasis.CORRECTED_WALL_CLOCK)
        confirmed_none = evaluate_structural_quality(
            self.night,
            time_basis=TimeBasis.CORRECTED_WALL_CLOCK,
            clock_corrections={
                self.session.record_id: ClockCorrectionEvidence(
                    ClockCorrectionEvidenceState.CONFIRMED_NONE,
                    source_record_ids=("oscar:corrections-query",),
                )
            },
        )

        self.assertNotEqual(without_input.record_id, confirmed_none.record_id)


def _provenance(name: str, *, availability: str | None = None) -> ProvenanceRecord:
    source_values = () if availability is None else (ProvenanceValue("signal.availability", availability),)
    return ProvenanceRecord(
        record_id=f"provenance:{name}",
        source_classes=(SourceClass.MACHINE_RECORDED, SourceClass.OSCAR_NORMALIZED),
        source_system="OSCAR",
        source_references=(SourceReference("test", name),),
        source_values=source_values,
    )


def _uniform_signal(
    signal_kind: str,
    unit: str,
    segment_specs: tuple[tuple[int, int, int], ...],
    *,
    timestamp_adjustment: float = 0.0,
) -> SignalRecord:
    provenance = _provenance(signal_kind, availability="available")
    segments = []
    for index, (start, end, sample_count) in enumerate(segment_specs):
        interval = (end - start) / sample_count
        times = tuple(start + sample_index * interval for sample_index in range(sample_count))
        if timestamp_adjustment and len(times) > 1:
            times = (times[0], times[1] + timestamp_adjustment, *times[2:])
        segments.append(
            SignalSegmentRecord(
                record_id=f"segment:{signal_kind}:{index}",
                start_time_ms=start,
                end_time_ms=end,
                interval_closure=IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                sample_times_ms=times,
                values=tuple(float(sample_index) for sample_index in range(sample_count)),
                sample_interval_ms=interval,
                provenance=provenance,
            )
        )
    return SignalRecord(
        record_id=f"signal:{signal_kind}",
        signal_kind=signal_kind,
        unit=unit,
        representation=SignalRepresentation.UNIFORM_WAVEFORM,
        segments=tuple(segments),
        provenance=provenance,
    )


def _timed_signal(
    signal_kind: str,
    unit: str,
    segment_samples: tuple[tuple[int, ...], ...],
    *,
    segment_end: int | None = None,
) -> SignalRecord:
    provenance = _provenance(signal_kind, availability="available")
    segments = tuple(
        SignalSegmentRecord(
            record_id=f"segment:{signal_kind}:{index}",
            start_time_ms=times[0],
            end_time_ms=times[-1] if segment_end is None else segment_end,
            interval_closure=IntervalClosure.START_AND_END_INCLUSIVE,
            sample_times_ms=times,
            values=tuple(float(sample_index) for sample_index in range(len(times))),
            sample_interval_ms=None,
            provenance=provenance,
        )
        for index, times in enumerate(segment_samples)
    )
    return SignalRecord(
        record_id=f"signal:{signal_kind}",
        signal_kind=signal_kind,
        unit=unit,
        representation=SignalRepresentation.TIMED_UPDATES,
        segments=segments,
        provenance=provenance,
    )


def _session(
    record_id: str,
    start: int,
    end: int,
    signals: tuple[SignalRecord, ...],
    provenance: ProvenanceRecord,
) -> SessionRecord:
    return SessionRecord(record_id, "device:test", start, end, (), (), signals, provenance)


def _night(sessions: tuple[SessionRecord, ...]) -> NightRecord:
    return NightRecord("night:2026-09-01", "2026-09-01", "America/Denver", "12:00:00", sessions, _provenance("night"))


if __name__ == "__main__":
    unittest.main()
