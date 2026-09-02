"""Fixed-fixture tests for version-1 signal quality findings."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from pap_pilot.engine import (
    EventRecord,
    IntervalClosure,
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
    ClockCorrectionEvidenceState,
    QualityImpact,
    QualityModelError,
    QualityRule,
    QualityStatus,
    ValidatedBreath,
    ValidatedBreathSeries,
    evaluate_large_leak,
    evaluate_likely_wake_breathing,
    evaluate_signal_artifacts,
    evaluate_signal_quality,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "signal-quality-v1.json"


class SignalQualityTests(unittest.TestCase):
    """Exercise the frozen S20 cases and conservative insufficient-evidence paths."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_fixed_fixture_metadata_matches_the_quality_contract(self) -> None:
        self.assertEqual(self.fixture["fixture_id"], "pap-pilot-signal-quality")
        self.assertEqual(self.fixture["fixture_version"], 1)
        self.assertEqual(self.fixture["source_kind"], "wholly_synthetic_signal_quality_cases")
        self.assertEqual(self.fixture["rule_set_id"], QUALITY_RULE_SET_ID)
        self.assertEqual(self.fixture["rule_set_version"], QUALITY_RULE_SET_VERSION)

    def test_fixed_large_leak_fixture_retains_threshold_and_machine_evidence(self) -> None:
        case = self.fixture["large_leak"]
        leak = _leak_signal(tuple((time, value) for time, value in case["updates"]))
        events = tuple(_event(f"event:large-leak:{index}", "large_leak", start, duration) for index, (start, duration) in enumerate(case["machine_events"]))
        session = _session(case["session_end_time_ms"], signals=(leak,), events=events)

        findings = evaluate_large_leak(session)

        actual = sorted((finding.reason_code, finding.start_time_ms, finding.end_time_ms) for finding in findings if finding.status is QualityStatus.FLAGGED)
        expected = sorted(tuple(value) for value in case["expected_flagged"])
        self.assertEqual(actual, expected)
        threshold, machine = (next(finding for finding in findings if finding.reason_code == reason) for reason in ("threshold_exceeded", "machine_large_leak_span"))
        self.assertEqual(threshold.impact, QualityImpact.EXCLUDE_INTERVAL)
        self.assertEqual(machine.impact, QualityImpact.EXCLUDE_INTERVAL)
        self.assertNotEqual(threshold.source_record_ids, machine.source_record_ids)
        self.assertFalse(any(finding.evaluated_record_id == "event:large-leak:1" for finding in findings))
        machine_measurements = {value.name: value.value for value in machine.measurements}
        self.assertEqual(machine_measurements["raw_end_time_ms"], 12_000)
        self.assertEqual(machine_measurements["clipped_duration_ms"], 6_000)
        self.assertEqual(machine_measurements["event_completeness"], "unknown")

    def test_large_leak_threshold_boundary_is_inclusive(self) -> None:
        below = _session(2_000, signals=(_leak_signal(((0, 23.999), (1_000, 23.999), (2_000, 23.999))),))
        equal = _session(2_000, signals=(_leak_signal(((0, 23.999), (1_000, 24.0), (2_000, 0.0))),))

        below_findings = evaluate_large_leak(below)
        equal_findings = evaluate_large_leak(equal)

        self.assertEqual([(finding.status, finding.reason_code) for finding in below_findings], [(QualityStatus.PASS, "condition_not_observed")])
        flagged = [finding for finding in equal_findings if finding.status is QualityStatus.FLAGGED]
        self.assertEqual([(finding.reason_code, finding.start_time_ms, finding.end_time_ms) for finding in flagged], [("threshold_exceeded", 1_000, 2_000)])

    def test_sparse_final_update_is_point_evidence_and_is_not_held(self) -> None:
        leak = _leak_signal(((0, 5.0), (1_000, 24.0)), segment_end=2_000)
        session = _session(2_000, signals=(leak,))

        findings = evaluate_large_leak(session)

        point = next(finding for finding in findings if finding.status is QualityStatus.FLAGGED)
        self.assertEqual((point.reason_code, point.start_time_ms, point.end_time_ms, point.impact), ("threshold_exceeded", None, None, QualityImpact.CAUTION))
        self.assertTrue(any(finding.reason_code == "leak_evidence_missing" and (finding.start_time_ms, finding.end_time_ms) == (1_000, 2_000) for finding in findings))

    def test_machine_large_leak_remains_flagged_when_trace_is_missing(self) -> None:
        event = _event("event:large-leak", "large_leak", 500, 1_000)
        session = _session(2_000, signals=(), events=(event,))

        findings = evaluate_large_leak(session)

        self.assertEqual({(finding.status, finding.reason_code) for finding in findings}, {(QualityStatus.FLAGGED, "machine_large_leak_span"), (QualityStatus.INSUFFICIENT_EVIDENCE, "leak_evidence_missing")})

    def test_large_leak_rejects_total_leak_and_reports_trace_gaps(self) -> None:
        total_leak = replace(_leak_signal(((0, 1.0), (2_000, 1.0))), value_semantics="total")
        unsupported = evaluate_large_leak(_session(2_000, signals=(total_leak,)))[0]
        gapped = _leak_signal(((0, 1.0), (500, 1.0)), segment_end=500)
        gap_findings = evaluate_large_leak(_session(2_000, signals=(gapped,)))

        self.assertEqual((unsupported.status, unsupported.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "unsupported_leak_contract"))
        self.assertTrue(any(finding.reason_code == "leak_evidence_missing" and (finding.start_time_ms, finding.end_time_ms) == (500, 2_000) for finding in gap_findings))

    def test_fixed_flow_impulse_fixture_matches_the_exact_interval(self) -> None:
        case = self.fixture["flow_impulse"]
        signal = _waveform("flow_rate", "L/min", tuple(case["raw_values"]), case["gain"], case["offset"])
        findings = evaluate_signal_artifacts(_session(len(case["raw_values"]) * 40, signals=(signal,)), "flow_rate")

        actual = sorted((finding.reason_code, finding.start_time_ms, finding.end_time_ms) for finding in findings if finding.status is QualityStatus.FLAGGED)
        self.assertEqual(actual, sorted(tuple(value) for value in case["expected_flagged"]))
        self.assertFalse(any(finding.reason_code == "digital_clipping" for finding in findings))

    def test_fixed_pressure_clipping_fixture_reconstructs_signed_raw_endpoint(self) -> None:
        case = self.fixture["pressure_clipping"]
        signal = _waveform("mask_pressure", "cm H₂O", tuple(case["raw_values"]), case["gain"], case["offset"])
        findings = evaluate_signal_artifacts(_session(len(case["raw_values"]) * 40, signals=(signal,)), "mask_pressure")

        actual = [(finding.reason_code, finding.start_time_ms, finding.end_time_ms) for finding in findings if finding.status is QualityStatus.FLAGGED]
        self.assertEqual(actual, [tuple(value) for value in case["expected_flagged"]])
        clipping = next(finding for finding in findings if finding.reason_code == "digital_clipping")
        measurements = {value.name: value.value for value in clipping.measurements}
        parameters = {value.name: value.value for value in clipping.parameters}
        self.assertEqual(measurements["reconstructed_raw_value"], -32_768)
        self.assertEqual(parameters["source_gain_per_raw_unit"], case["gain"])
        self.assertEqual(parameters["source_offset"], case["offset"])

    def test_positive_signed_raw_endpoint_is_also_digital_clipping(self) -> None:
        signal = _waveform("flow_rate", "L/min", (32_767, 0, 0), 0.1, 0.0)

        findings = evaluate_signal_artifacts(_session(120, signals=(signal,)), "flow_rate")

        clipping = next(finding for finding in findings if finding.reason_code == "digital_clipping")
        measurements = {value.name: value.value for value in clipping.measurements}
        self.assertEqual(measurements["reconstructed_raw_value"], 32_767)

    def test_impulse_thresholds_and_neighbor_tolerances_are_inclusive(self) -> None:
        flow_equal = _waveform_from_values("flow_rate", "L/min", (0.0, 33.0, 3.0), gain=0.1, offset=0.0)
        flow_below = _waveform_from_values("flow_rate", "L/min", (0.0, 32.999, 3.0), gain=0.1, offset=0.0)
        pressure_equal = _waveform_from_values("mask_pressure", "cm H₂O", (0.0, 3.3, 0.3), gain=0.01, offset=0.0)

        flow_equal_findings = evaluate_signal_artifacts(_session(120, signals=(flow_equal,)), "flow_rate")
        flow_below_findings = evaluate_signal_artifacts(_session(120, signals=(flow_below,)), "flow_rate")
        pressure_equal_findings = evaluate_signal_artifacts(_session(120, signals=(pressure_equal,)), "mask_pressure")

        self.assertTrue(any(finding.reason_code == "isolated_impulse" for finding in flow_equal_findings))
        self.assertFalse(any(finding.reason_code == "isolated_impulse" for finding in flow_below_findings))
        self.assertTrue(any(finding.reason_code == "isolated_impulse" for finding in pressure_equal_findings))

    def test_artifact_detectors_pass_flat_waveform_without_calling_it_artifact(self) -> None:
        signal = _waveform_from_values("flow_rate", "L/min", (0.0, 0.0, 0.0, 0.0), gain=0.1, offset=0.0)

        findings = evaluate_signal_artifacts(_session(160, signals=(signal,)), "flow_rate")

        self.assertEqual(len(findings), 2)
        self.assertEqual({finding.status for finding in findings}, {QualityStatus.PASS})
        self.assertEqual({finding.reason_code for finding in findings}, {"condition_not_observed"})

    def test_artifact_detection_never_crosses_segments(self) -> None:
        first = _waveform_from_values("flow_rate", "L/min", (0.0, 0.0), gain=0.1, offset=0.0, start=0, record_suffix="first")
        second = _waveform_from_values("flow_rate", "L/min", (40.0, 0.0), gain=0.1, offset=0.0, start=120, record_suffix="second")
        signal = replace(first, segments=first.segments + second.segments)

        findings = evaluate_signal_artifacts(_session(200, signals=(signal,)), "flow_rate")

        self.assertFalse(any(finding.reason_code == "isolated_impulse" for finding in findings))
        self.assertTrue(any(finding.status is QualityStatus.INSUFFICIENT_EVIDENCE for finding in findings))

    def test_missing_artifact_inputs_are_insufficient_and_other_signals_are_not_applicable(self) -> None:
        signal = _waveform_from_values("flow_rate", "L/min", (0.0, 1.0, 0.0), gain=None, offset=None)
        missing_gain = evaluate_signal_artifacts(_session(120, signals=(signal,)), "flow_rate")
        absent = evaluate_signal_artifacts(_session(120), "mask_pressure")
        other = evaluate_signal_artifacts(_session(120), "leak_rate")

        self.assertTrue(any(finding.status is QualityStatus.INSUFFICIENT_EVIDENCE and finding.reason_code == "artifact_input_missing" for finding in missing_gain))
        self.assertEqual((absent[0].status, absent[0].reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "artifact_input_missing"))
        self.assertEqual((other[0].status, other[0].reason_code), (QualityStatus.NOT_APPLICABLE, "rule_not_applicable"))

    def test_non_40_ms_waveform_is_insufficient_for_artifact_detection(self) -> None:
        signal = _waveform_from_values("flow_rate", "L/min", (0.0, 1.0, 0.0), gain=0.1, offset=0.0, sample_interval=50.0)

        finding = evaluate_signal_artifacts(_session(150, signals=(signal,)), "flow_rate")[0]

        self.assertEqual((finding.status, finding.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "artifact_input_missing"))

    def test_fixed_likely_wake_fixture_flags_three_overlapping_irregular_windows(self) -> None:
        case = self.fixture["likely_wake"]
        session = _wake_session(sum(case["durations_ms"]))
        series = _breath_series(session, tuple(case["durations_ms"]), tuple(case["peak_to_trough_l_min"]), case["detector_id"], case["detector_version"])

        findings = evaluate_likely_wake_breathing(session, series)

        actual = [(finding.reason_code, finding.start_time_ms, finding.end_time_ms) for finding in findings if finding.status is QualityStatus.FLAGGED]
        self.assertEqual(actual, [tuple(value) for value in case["expected_flagged"]])
        candidate = next(finding for finding in findings if finding.reason_code == "irregular_breathing_candidate")
        measurements = {value.name: value.value for value in candidate.measurements}
        parameters = {value.name: value.value for value in candidate.parameters}
        self.assertEqual(measurements["irregular_window_count"], case["expected_irregular_window_count"])
        self.assertEqual((parameters["breath_detector_id"], parameters["breath_detector_version"]), (case["detector_id"], case["detector_version"]))
        self.assertIn("not confirmed wake", candidate.limitations[0].lower())

    def test_fixed_fixture_outputs_are_versioned_companion_findings(self) -> None:
        leak_case = self.fixture["large_leak"]
        leak = _leak_signal(tuple((time, value) for time, value in leak_case["updates"]))
        leak_findings = evaluate_large_leak(_session(leak_case["session_end_time_ms"], signals=(leak,)))
        impulse_case = self.fixture["flow_impulse"]
        flow = _waveform("flow_rate", "L/min", tuple(impulse_case["raw_values"]), impulse_case["gain"], impulse_case["offset"])
        artifact_findings = evaluate_signal_artifacts(_session(len(impulse_case["raw_values"]) * 40, signals=(flow,)), "flow_rate")
        wake_case = self.fixture["likely_wake"]
        wake_session = _wake_session(sum(wake_case["durations_ms"]))
        breaths = _breath_series(wake_session, tuple(wake_case["durations_ms"]), tuple(wake_case["peak_to_trough_l_min"]))
        wake_findings = evaluate_likely_wake_breathing(wake_session, breaths)

        for finding in (*leak_findings, *artifact_findings, *wake_findings):
            self.assertEqual((finding.rule_set_id, finding.rule_set_version), (QUALITY_RULE_SET_ID, QUALITY_RULE_SET_VERSION))
            self.assertEqual(finding.source_class, SourceClass.COMPANION_DERIVED)

        with self.assertRaises(QualityModelError):
            replace(wake_findings[0], reason_code="invented_reason")

    def test_regular_breathing_passes_without_claiming_sleep(self) -> None:
        session = _wake_session(7_000)
        series = _breath_series(session, (1_000,) * 7, (10.0,) * 7)

        finding = evaluate_likely_wake_breathing(session, series)[0]

        self.assertEqual((finding.status, finding.reason_code), (QualityStatus.PASS, "condition_not_observed"))
        self.assertTrue(any("does not prove sleep" in limitation for limitation in finding.limitations))

    def test_wake_cv_boundaries_are_inclusive(self) -> None:
        duration_at = (600, 1_100, 1_100, 1_100, 1_100, 600, 1_100)
        amplitude_at = (8.0, 23.0, 23.0, 23.0, 23.0, 8.0, 23.0)
        duration_below = (601, 1_100, 1_100, 1_100, 1_100, 601, 1_100)
        session = _wake_session(10_000)
        at_series = _breath_series(session, duration_at, amplitude_at)
        below_series = _breath_series(session, duration_below, amplitude_at)

        at_findings = evaluate_likely_wake_breathing(session, at_series)
        below_findings = evaluate_likely_wake_breathing(session, below_series)

        self.assertTrue(any(finding.reason_code == "irregular_breathing_candidate" for finding in at_findings))
        self.assertFalse(any(finding.reason_code == "irregular_breathing_candidate" for finding in below_findings))

    def test_missing_or_too_few_validated_breaths_are_insufficient(self) -> None:
        session = _wake_session(7_000)
        missing = evaluate_likely_wake_breathing(session, None)[0]
        short_series = _breath_series(session, (1_000,) * 6, (10.0,) * 6)
        too_few = evaluate_likely_wake_breathing(session, short_series)[0]

        self.assertEqual((missing.status, missing.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "wake_prerequisite_missing"))
        self.assertEqual((too_few.status, too_few.reason_code), (QualityStatus.INSUFFICIENT_EVIDENCE, "too_few_eligible_breaths"))

    def test_source_event_and_three_recovery_breaths_are_suppressed(self) -> None:
        event = _event("event:oa", "obstructive_apnea", 0, 1_000)
        session = _wake_session(10_000, events=(event,))
        series = _breath_series(session, (1_000,) * 10, (10.0,) * 10)

        finding = next(finding for finding in evaluate_likely_wake_breathing(session, series) if finding.reason_code == "too_few_eligible_breaths")

        measurements = {value.name: value.value for value in finding.measurements}
        self.assertEqual(measurements["eligible_breath_count"], 6)
        self.assertEqual(measurements["longest_consecutive_eligible_run"], 6)
        self.assertIn(event.record_id, finding.source_record_ids)

    def test_leak_prerequisite_blocks_only_its_interval_before_wake_analysis(self) -> None:
        session = _wake_session(7_000, leak_updates=((0, 5.0), (1_000, 24.0), (2_000, 5.0), (7_000, 5.0)))
        case = self.fixture["likely_wake"]
        series = _breath_series(session, tuple(case["durations_ms"]), tuple(case["peak_to_trough_l_min"]))

        findings = evaluate_likely_wake_breathing(session, series)

        blocked = next(finding for finding in findings if finding.reason_code == "wake_prerequisite_missing")
        self.assertEqual((blocked.start_time_ms, blocked.end_time_ms), (1_000, 2_000))
        self.assertFalse(any(finding.reason_code == "irregular_breathing_candidate" for finding in findings))

    def test_breath_series_is_immutable_versioned_detector_input_with_strict_identity(self) -> None:
        session = _wake_session(7_000)
        series = _breath_series(session, (1_000,) * 7, (10.0,) * 7)
        wrong = replace(series, session_record_id="session:other")

        with self.assertRaises(FrozenInstanceError):
            series.detector_version = "2"  # type: ignore[misc]
        with self.assertRaises(QualityModelError):
            evaluate_likely_wake_breathing(session, wrong)
        with self.assertRaises(QualityModelError):
            replace(series, source_record_ids=("segment:unrelated",))
        with self.assertRaises(QualityModelError):
            replace(series.breaths[0], peak_to_trough_l_min=0.0)

    def test_signal_quality_report_is_deterministic_versioned_and_dependency_ordered(self) -> None:
        session = _wake_session(7_000)
        series = _breath_series(session, (1_000,) * 7, (10.0,) * 7)

        report = evaluate_signal_quality(session, series)
        repeated = evaluate_signal_quality(session, series)

        self.assertEqual(report, repeated)
        self.assertEqual((report.rule_set_id, report.rule_set_version), (QUALITY_RULE_SET_ID, QUALITY_RULE_SET_VERSION))
        first_positions = {rule: min(index for index, finding in enumerate(report.findings) if finding.rule_id is rule) for rule in (QualityRule.LARGE_LEAK, QualityRule.SIGNAL_ARTIFACT, QualityRule.LIKELY_WAKE_BREATHING)}
        self.assertLess(first_positions[QualityRule.LARGE_LEAK], first_positions[QualityRule.SIGNAL_ARTIFACT])
        self.assertLess(first_positions[QualityRule.SIGNAL_ARTIFACT], first_positions[QualityRule.LIKELY_WAKE_BREATHING])
        self.assertEqual({finding.source_class for finding in report.findings}, {SourceClass.COMPANION_DERIVED})
        self.assertFalse(any(finding.rule_id in {QualityRule.MISSING_REQUIRED_SIGNAL, QualityRule.SHORT_SESSION} for finding in report.findings))
        with self.assertRaises(FrozenInstanceError):
            report.session_record_id = "session:changed"  # type: ignore[misc]

    def test_clock_state_import_remains_available_after_quality_exports_expand(self) -> None:
        self.assertEqual(ClockCorrectionEvidenceState.NOT_QUERIED.value, "not_queried")


def _provenance(name: str, values: dict[str, object] | None = None) -> ProvenanceRecord:
    source_values = tuple(ProvenanceValue(key, json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)) for key, value in (values or {}).items())
    return ProvenanceRecord(
        record_id=f"provenance:{name}",
        source_classes=(SourceClass.MACHINE_RECORDED, SourceClass.OSCAR_NORMALIZED),
        source_system="OSCAR",
        source_references=(SourceReference("synthetic_fixture", name),),
        source_values=source_values,
    )


def _event(record_id: str, event_kind: str, start: int, duration: int) -> EventRecord:
    return EventRecord(record_id, event_kind, start, duration, _provenance(record_id))


def _session(end: int, *, signals: tuple[SignalRecord, ...] = (), events: tuple[EventRecord, ...] = ()) -> SessionRecord:
    provenance = _provenance("session", {"events.completeness": "unknown"})
    return SessionRecord("session:fixture", "device:fixture", 0, end, (), events, signals, provenance)


def _leak_signal(updates: tuple[tuple[int, float], ...], *, segment_end: int | None = None) -> SignalRecord:
    provenance = _provenance("leak", {"signal.availability": "available"})
    times = tuple(time for time, _ in updates)
    values = tuple(value for _, value in updates)
    segment = SignalSegmentRecord(
        "segment:leak",
        times[0],
        times[-1] if segment_end is None else segment_end,
        IntervalClosure.START_AND_END_INCLUSIVE,
        times,
        values,
        None,
        _provenance("leak-segment", {"segment.gain_per_raw_unit": 1.0, "segment.offset": 0.0}),
    )
    return SignalRecord("signal:leak", "leak_rate", "L/min", SignalRepresentation.TIMED_UPDATES, (segment,), provenance, "unintentional")


def _waveform(signal_kind: str, unit: str, raw_values: tuple[int, ...], gain: float, offset: float) -> SignalRecord:
    return _waveform_from_values(signal_kind, unit, tuple(value * gain + offset for value in raw_values), gain=gain, offset=offset)


def _waveform_from_values(
    signal_kind: str,
    unit: str,
    values: tuple[float, ...],
    *,
    gain: float | None,
    offset: float | None,
    start: int = 0,
    record_suffix: str = "only",
    sample_interval: float = 40.0,
) -> SignalRecord:
    provenance_values = {}
    if gain is not None:
        provenance_values["segment.gain_per_raw_unit"] = gain
    if offset is not None:
        provenance_values["segment.offset"] = offset
    segment_provenance = _provenance(f"{signal_kind}-segment-{record_suffix}", provenance_values)
    segment = SignalSegmentRecord(
        f"segment:{signal_kind}:{record_suffix}",
        start,
        int(start + len(values) * sample_interval),
        IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
        tuple(start + index * sample_interval for index in range(len(values))),
        values,
        sample_interval,
        segment_provenance,
    )
    signal_provenance = _provenance(signal_kind, {"signal.availability": "available"})
    return SignalRecord(f"signal:{signal_kind}", signal_kind, unit, SignalRepresentation.UNIFORM_WAVEFORM, (segment,), signal_provenance)


def _wake_session(end: int, *, events: tuple[EventRecord, ...] = (), leak_updates: tuple[tuple[int, float], ...] | None = None) -> SessionRecord:
    sample_count = end // 40
    flow = _waveform_from_values("flow_rate", "L/min", (0.0,) * sample_count, gain=0.1, offset=0.0)
    leak = _leak_signal(((0, 5.0), (end, 5.0)) if leak_updates is None else leak_updates)
    return _session(end, signals=(flow, leak), events=events)


def _breath_series(
    session: SessionRecord,
    durations: tuple[float, ...] | tuple[int, ...],
    amplitudes: tuple[float, ...],
    detector_id: str = "pap-pilot.fixture-breaths",
    detector_version: str = "1",
) -> ValidatedBreathSeries:
    flow = next(signal for signal in session.signals if signal.signal_kind == "flow_rate")
    breaths = []
    cursor = 0.0
    for index, (duration, amplitude) in enumerate(zip(durations, amplitudes)):
        breaths.append(ValidatedBreath(f"breath:{index}", cursor, cursor + duration, amplitude))
        cursor += duration
    return ValidatedBreathSeries(
        "breath-series:fixture",
        session.record_id,
        flow.record_id,
        detector_id,
        detector_version,
        tuple(breaths),
        (flow.record_id, *(segment.record_id for segment in flow.segments)),
        (flow.provenance.record_id, *(segment.provenance.record_id for segment in flow.segments)),
    )


if __name__ == "__main__":
    unittest.main()
