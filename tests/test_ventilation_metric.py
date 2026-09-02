"""Hand-calculated fixture tests for metric-set v1 ventilation dispersion."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from pap_pilot.engine import EventRecord, IntervalClosure, NightRecord, ProvenanceRecord, ProvenanceValue, SessionRecord, SettingRecord, SignalRecord, SignalRepresentation, SignalSegmentRecord, SourceClass, SourceReference
from pap_pilot.engine.metrics import (
    METRIC_SET_ID,
    METRIC_SET_VERSION,
    MINIMUM_ELIGIBLE_DURATION_MS,
    MINIMUM_VENTILATION_OBSERVATIONS,
    MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION,
    VENTILATION_WINDOW_DURATION_MS,
    VENTILATION_WINDOW_STEP_MS,
    MetricId,
    MetricModelError,
    MetricReason,
    MetricStatus,
    evaluate_minute_ventilation_upper_tail_ratio,
)
from pap_pilot.engine.quality import QualityRule


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "minute-ventilation-upper-tail-ratio-v1.json"


class VentilationMetricTests(unittest.TestCase):
    """Exercise integration, windows, quantiles, boundaries, and provenance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_fixture_metadata_matches_the_accepted_metric_contract(self) -> None:
        self.assertEqual(self.fixture["fixture_id"], "pap-pilot-minute-ventilation-upper-tail-ratio")
        self.assertEqual(self.fixture["fixture_version"], 1)
        self.assertEqual(self.fixture["source_kind"], "wholly_synthetic_hand_calculated_cases")
        self.assertEqual((self.fixture["metric_set_id"], self.fixture["metric_set_version"]), (METRIC_SET_ID, METRIC_SET_VERSION))
        self.assertEqual(self.fixture["metric_id"], MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO.value)
        self.assertEqual(self.fixture["algorithm_version"], MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION)
        self.assertEqual(self.fixture["minimum_eligible_duration_ms"], MINIMUM_ELIGIBLE_DURATION_MS)
        self.assertEqual(self.fixture["window_duration_ms"], VENTILATION_WINDOW_DURATION_MS)
        self.assertEqual(self.fixture["window_step_ms"], VENTILATION_WINDOW_STEP_MS)
        self.assertEqual(self.fixture["minimum_observation_count"], MINIMUM_VENTILATION_OBSERVATIONS)

    def test_exactly_twenty_windows_match_hand_calculated_type_7_quantiles(self) -> None:
        case = self.fixture["cases"]["exactly_twenty_type_7"]
        intervals = _intervals_from_durations(tuple(case["eligible_run_durations_ms"]))
        long_values = _block_values(tuple((duration, value) for duration, value in case["long_run_flow_blocks"]))
        values = (long_values, *((1.0,) * ((end - start) // 40) for start, end in intervals[1:]))
        session = _session("only", intervals[0][0], intervals[-1][1], segments=tuple(zip(intervals, values)))

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))

        measurements = _measurements(result)
        self.assertEqual((result.status, result.reason_code, result.unit), (MetricStatus.CALCULATED, MetricReason.CALCULATED, "1"))
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.observation_count, case["expected_observation_count"])
        self.assertEqual(result.sample_cell_count, case["expected_sample_cell_count"])
        self.assertAlmostEqual(measurements["ventilation_q50_l_min"], case["expected_q50_l_min"])
        self.assertAlmostEqual(measurements["ventilation_q95_l_min"], case["expected_q95_l_min"])
        self.assertAlmostEqual(result.value, case["expected_ratio"])

    def test_nineteen_windows_are_insufficient_despite_exact_minimum_duration(self) -> None:
        case = self.fixture["cases"]["nineteen_windows"]
        intervals = _intervals_from_durations(tuple(case["eligible_run_durations_ms"]))
        segments = tuple((interval, (10.0,) * ((interval[1] - interval[0]) // 40)) for interval in intervals)

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((_session("only", intervals[0][0], intervals[-1][1], segments=segments),)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.TOO_FEW_VENTILATION_WINDOWS))
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.observation_count, case["expected_observation_count"])

    def test_one_millisecond_below_minimum_duration_takes_precedence(self) -> None:
        case = self.fixture["cases"]["one_ms_below"]
        start, end = case["excluded_interval_ms"]
        session = _session("only", 0, case["requested_duration_ms"], flow_value=10.0, events=(_large_leak_event("last-ms", start, end - start),))

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.ELIGIBLE_DURATION_BELOW_300000_MS))
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertGreaterEqual(result.observation_count, MINIMUM_VENTILATION_OBSERVATIONS)

    def test_positive_flow_integration_clamps_expiration_and_uses_one_second_steps(self) -> None:
        case = self.fixture["cases"]["positive_flow_only"]
        count = case["requested_duration_ms"] // 40
        positive, negative = case["alternating_flow_l_min"]
        values = tuple(positive if index % 2 == 0 else negative for index in range(count))
        session = _session("only", 0, case["requested_duration_ms"], flow_values=values)

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))

        measurements = _measurements(result)
        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.observation_count, case["expected_observation_count"])
        self.assertEqual(measurements["ventilation_q50_l_min"], case["expected_q50_l_min"])
        self.assertEqual(measurements["ventilation_q95_l_min"], case["expected_q95_l_min"])
        self.assertEqual(result.value, case["expected_ratio"])

    def test_partial_flow_cells_are_integrated_at_exact_window_boundaries(self) -> None:
        case = self.fixture["cases"]["partial_sample_cell"]
        start, end = case["excluded_interval_ms"]
        session = _session("only", 0, case["requested_duration_ms"], flow_value=10.0, events=(_large_leak_event("partial", start, end - start),))

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))

        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.observation_count, case["expected_observation_count"])
        self.assertEqual(result.sample_cell_count, case["expected_sample_cell_count"])
        self.assertEqual(result.value, case["expected_ratio"])

    def test_overlapping_large_leak_and_flow_artifact_are_unioned(self) -> None:
        case = self.fixture["cases"]["overlapping_leak_and_artifact"]
        count = case["requested_duration_ms"] // 40
        flow = [10.0] * count
        flow[2] = 50.0
        leak_start, leak_end = case["large_leak_interval_ms"]
        leak_updates = ((0, 5.0), (leak_start, 24.0), (leak_end, 5.0), (case["requested_duration_ms"], 5.0))
        session = _session("only", 0, case["requested_duration_ms"], flow_values=tuple(flow), leak_updates=leak_updates)

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))

        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.value, case["expected_ratio"])
        excluded = next(value for value in result.excluded_intervals if (value.start_time_ms, value.end_time_ms) == tuple(case["expected_excluded_interval_ms"]))
        self.assertEqual(set(excluded.reason_codes), {"isolated_impulse", "threshold_exceeded"})
        self.assertEqual(len(excluded.quality_finding_ids), 2)

    def test_windows_never_cross_segment_gaps(self) -> None:
        case = self.fixture["cases"]["exactly_twenty_type_7"]
        intervals = _intervals_from_durations(tuple(case["eligible_run_durations_ms"]))
        segments = tuple((interval, (10.0,) * ((interval[1] - interval[0]) // 40)) for interval in intervals)

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((_session("only", intervals[0][0], intervals[-1][1], segments=segments),)))

        self.assertEqual(result.observation_count, 20)
        self.assertEqual(len(result.eligible_intervals), 5)
        self.assertEqual(result.excluded_duration_ms, 4_000)
        self.assertTrue(all(len(value.source_segment_ids) == 2 for value in result.eligible_intervals))

    def test_split_sessions_pool_windows_but_never_bridge_the_gap(self) -> None:
        case = self.fixture["cases"]["split_sessions"]
        (first_start, first_end), (second_start, second_end) = case["session_intervals_ms"]
        first_flow, second_flow = case["flow_l_min"]
        first = _session("first", first_start, first_end, flow_value=first_flow)
        second = _session("second", second_start, second_end, flow_value=second_flow)

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((second, first)))

        measurements = _measurements(result)
        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.observation_count, case["expected_observation_count"])
        self.assertEqual(measurements["ventilation_q50_l_min"], case["expected_q50_l_min"])
        self.assertEqual(measurements["ventilation_q95_l_min"], case["expected_q95_l_min"])
        self.assertEqual(result.value, case["expected_ratio"])
        self.assertFalse(result.excluded_intervals)

    def test_inconsistent_split_session_settings_are_insufficient(self) -> None:
        first = _session("first", 0, 150_000, flow_value=10.0)
        second = _session("second", 151_000, 301_000, flow_value=10.0, ps_min=2.0)

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((first, second)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.SETTINGS_INCONSISTENT))
        self.assertEqual(result.eligible_duration_ms, 0)

    def test_nonpositive_median_returns_insufficient_with_supporting_quantiles(self) -> None:
        case = self.fixture["cases"]["nonpositive_median"]
        session = _session("only", 0, case["requested_duration_ms"], flow_value=case["flow_l_min"])

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))

        self.assertEqual((result.status, result.reason_code, result.value, result.unit), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.NONPOSITIVE_VENTILATION_MEDIAN, None, None))
        self.assertEqual(result.observation_count, case["expected_observation_count"])
        self.assertEqual(_measurements(result), {"ventilation_q50_l_min": 0.0, "ventilation_q95_l_min": 0.0})

    def test_mask_pressure_is_not_an_input_or_quality_dependency(self) -> None:
        session = _session("only", 0, 300_000, flow_value=10.0)
        without_pressure = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))
        unsupported_pressure = SignalRecord("signal:mask-pressure:irrelevant", "mask_pressure", "unsupported", SignalRepresentation.UNIFORM_WAVEFORM, (), _provenance("irrelevant-pressure"))
        with_pressure = evaluate_minute_ventilation_upper_tail_ratio(_night((replace(session, signals=(*session.signals, unsupported_pressure)),)))

        self.assertEqual(without_pressure, with_pressure)
        self.assertNotIn(unsupported_pressure.record_id, with_pressure.source_record_ids)

    def test_missing_and_unsupported_required_inputs_have_stable_reasons(self) -> None:
        complete = _session("only", 0, 300_000, flow_value=10.0)
        missing_setting = replace(complete, settings=complete.settings[:-1])
        missing_flow = replace(complete, signals=tuple(signal for signal in complete.signals if signal.signal_kind != "flow_rate"))
        flow = next(signal for signal in complete.signals if signal.signal_kind == "flow_rate")
        unsupported_flow = replace(flow, unit="mL/s")
        unsupported = replace(complete, signals=tuple(unsupported_flow if signal.signal_kind == "flow_rate" else signal for signal in complete.signals))

        cases = (
            (missing_setting, MetricReason.SETTINGS_UNAVAILABLE),
            (missing_flow, MetricReason.REQUIRED_SIGNAL_UNAVAILABLE),
            (unsupported, MetricReason.UNSUPPORTED_SIGNAL_CONTRACT),
        )
        for session, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_minute_ventilation_upper_tail_ratio(_night((session,)))
                self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, reason))

    def test_disjoint_flow_and_leak_coverage_is_an_unresolved_quality_prerequisite(self) -> None:
        session = _session("only", 0, 300_000, flow_value=10.0)
        flow = _flow_signal("only", ((((0, 150_000), (10.0,) * 3_750)),))
        leak = _leak_signal("only", ((150_000, 300_000),))
        disjoint = replace(session, signals=(flow, leak))

        result = evaluate_minute_ventilation_upper_tail_ratio(_night((disjoint,)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.QUALITY_PREREQUISITE_UNRESOLVED))
        self.assertEqual(result.eligible_duration_ms, 0)

    def test_missing_likely_wake_prerequisite_is_retained_without_exclusion(self) -> None:
        result = evaluate_minute_ventilation_upper_tail_ratio(_night((_session("only", 0, 300_000, flow_value=10.0),)))

        wake_ids = tuple(identifier for identifier in result.quality_finding_ids if identifier.startswith(f"quality:{QualityRule.LIKELY_WAKE_BREATHING.value}:"))
        excluded_ids = {identifier for interval in result.excluded_intervals for identifier in interval.quality_finding_ids}
        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(len(wake_ids), 1)
        self.assertTrue(excluded_ids.isdisjoint(wake_ids))
        self.assertTrue(any("does not establish sleep" in limitation for limitation in result.limitations))

    def test_result_is_deterministic_immutable_and_provenance_complete(self) -> None:
        night = _night((_session("only", 0, 300_000, flow_value=10.0),))

        result = evaluate_minute_ventilation_upper_tail_ratio(night)
        repeated = evaluate_minute_ventilation_upper_tail_ratio(night)

        self.assertEqual(result, repeated)
        self.assertEqual(result.record_id, repeated.record_id)
        self.assertEqual(result.metric_id, MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO)
        self.assertEqual(len(result.settings), 6)
        self.assertTrue({"signal:only:flow_rate", "signal:only:leak_rate"}.issubset(result.source_record_ids))
        self.assertTrue(result.quality_report_ids)
        self.assertTrue(result.quality_finding_ids)
        self.assertEqual(result.source_class, SourceClass.COMPANION_DERIVED)
        with self.assertRaises(FrozenInstanceError):
            result.value = 0.0  # type: ignore[misc]
        with self.assertRaises(MetricModelError):
            replace(result, observation_count=19)


def _measurements(result) -> dict[str, float]:
    return {value.name: value.value for value in result.measurements}


def _provenance(name: str, values: dict[str, object] | None = None) -> ProvenanceRecord:
    source_values = tuple(ProvenanceValue(key, json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)) for key, value in (values or {}).items())
    return ProvenanceRecord(f"provenance:{name}", (SourceClass.MACHINE_RECORDED, SourceClass.OSCAR_NORMALIZED), "synthetic_fixture", (SourceReference("fixture", name),), source_values=source_values)


def _settings(suffix: str, *, ps_min: float = 1.0) -> tuple[SettingRecord, ...]:
    values = (
        ("therapy_mode_code", 6, None),
        ("loader_mode_code", 7, None),
        ("epap", 10.0, "cm H₂O"),
        ("ps_min", ps_min, "cm H₂O"),
        ("ps_max", 5.0, "cm H₂O"),
        ("max_ipap", 15.0, "cm H₂O"),
    )
    return tuple(SettingRecord(f"setting:{suffix}:{name}", name, value, unit, _provenance(f"setting-{suffix}-{name}")) for name, value, unit in values)


def _flow_signal(suffix: str, segments: tuple[tuple[tuple[int, int], tuple[float, ...]], ...], *, unit: str = "L/min") -> SignalRecord:
    records = []
    for index, ((start, end), values) in enumerate(segments):
        count = (end - start) // 40
        if len(values) != count:
            raise AssertionError("Flow fixture values must match the 40 ms segment duration.")
        records.append(SignalSegmentRecord(f"segment:{suffix}:flow_rate:{index}", start, end, IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE, tuple(float(start + sample * 40) for sample in range(count)), values, 40.0, _provenance(f"segment-{suffix}-flow-{index}", {"segment.gain_per_raw_unit": 0.1, "segment.offset": 0.0})))
    return SignalRecord(f"signal:{suffix}:flow_rate", "flow_rate", unit, SignalRepresentation.UNIFORM_WAVEFORM, tuple(records), _provenance(f"signal-{suffix}-flow", {"signal.availability": "available"}))


def _leak_signal(suffix: str, intervals: tuple[tuple[int, int], ...], updates: tuple[tuple[int, float], ...] | None = None) -> SignalRecord:
    samples_by_segment = (updates,) if updates is not None else tuple(((start, 5.0), (end, 5.0)) for start, end in intervals)
    segments = tuple(
        SignalSegmentRecord(
            f"segment:{suffix}:leak_rate:{index}",
            samples[0][0],
            samples[-1][0],
            IntervalClosure.START_AND_END_INCLUSIVE,
            tuple(time for time, _ in samples),
            tuple(value for _, value in samples),
            None,
            _provenance(f"segment-{suffix}-leak-{index}", {"segment.gain_per_raw_unit": 0.1, "segment.offset": 0.0}),
        )
        for index, samples in enumerate(samples_by_segment)
    )
    return SignalRecord(f"signal:{suffix}:leak_rate", "leak_rate", "L/min", SignalRepresentation.TIMED_UPDATES, segments, _provenance(f"signal-{suffix}-leak", {"signal.availability": "available"}), "unintentional")


def _large_leak_event(suffix: str, start: int, duration: int) -> EventRecord:
    return EventRecord(f"event:{suffix}", "large_leak", start, duration, _provenance(f"event-{suffix}"))


def _session(
    suffix: str,
    start: int,
    end: int,
    *,
    flow_value: float = 10.0,
    flow_values: tuple[float, ...] | None = None,
    segments: tuple[tuple[tuple[int, int], tuple[float, ...]], ...] | None = None,
    leak_updates: tuple[tuple[int, float], ...] | None = None,
    events: tuple[EventRecord, ...] = (),
    ps_min: float = 1.0,
) -> SessionRecord:
    if segments is None:
        count = (end - start) // 40
        intervals = ((start, end),)
        segment_values = flow_values or (flow_value,) * count
        segments = (((start, end), segment_values),)
    else:
        intervals = tuple(interval for interval, _ in segments)
    signals = (_flow_signal(suffix, segments), _leak_signal(suffix, intervals, leak_updates))
    return SessionRecord(f"session:{suffix}", "device:fixture", start, end, _settings(suffix, ps_min=ps_min), events, signals, _provenance(f"session-{suffix}", {"events.completeness": "unknown"}))


def _night(sessions: tuple[SessionRecord, ...]) -> NightRecord:
    return NightRecord("night:fixture", "2026-09-02", "America/Denver", "12:00:00", sessions, _provenance("night"))


def _intervals_from_durations(durations: tuple[int, ...], gap_ms: int = 1_000) -> tuple[tuple[int, int], ...]:
    intervals = []
    start = 0
    for duration in durations:
        intervals.append((start, start + duration))
        start += duration + gap_ms
    return tuple(intervals)


def _block_values(blocks: tuple[tuple[int, float], ...]) -> tuple[float, ...]:
    if any(duration % 40 for duration, _ in blocks):
        raise AssertionError("Each Flow Rate block must align to 40 ms cells.")
    return tuple(value for duration, value in blocks for _ in range(duration // 40))
