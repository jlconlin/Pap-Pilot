"""Hand-calculated fixture tests for metric-set v1 pressure exposure."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from pap_pilot.engine import (
    EventRecord,
    IntervalClosure,
    NightRecord,
    ProvenanceRecord,
    ProvenanceValue,
    SessionRecord,
    SettingRecord,
    SignalRecord,
    SignalRepresentation,
    SignalSegmentRecord,
    SourceClass,
    SourceReference,
)
from pap_pilot.engine.metrics import (
    MEAN_MASK_PRESSURE_ABOVE_EPAP_ALGORITHM_VERSION,
    METRIC_SET_ID,
    METRIC_SET_VERSION,
    MINIMUM_ELIGIBLE_DURATION_MS,
    MetricModelError,
    MetricReason,
    MetricStatus,
    evaluate_mean_mask_pressure_above_epap,
)
from pap_pilot.engine.quality import QualityRule


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mean-mask-pressure-above-epap-v1.json"


class PressureMetricTests(unittest.TestCase):
    """Exercise formula, boundaries, interval rules, quality, and provenance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_fixture_metadata_matches_the_accepted_metric_contract(self) -> None:
        self.assertEqual(self.fixture["fixture_id"], "pap-pilot-mean-mask-pressure-above-epap")
        self.assertEqual(self.fixture["fixture_version"], 1)
        self.assertEqual(self.fixture["source_kind"], "wholly_synthetic_hand_calculated_cases")
        self.assertEqual((self.fixture["metric_set_id"], self.fixture["metric_set_version"]), (METRIC_SET_ID, METRIC_SET_VERSION))
        self.assertEqual(self.fixture["algorithm_version"], MEAN_MASK_PRESSURE_ABOVE_EPAP_ALGORITHM_VERSION)
        self.assertEqual(self.fixture["minimum_eligible_duration_ms"], MINIMUM_ELIGIBLE_DURATION_MS)

    def test_exact_minimum_uses_duration_weighting_and_clamps_below_epap(self) -> None:
        case = self.fixture["cases"]["exact_minimum"]
        pressure = _block_values(tuple((duration, value) for duration, value in case["pressure_blocks"]))
        night = _night((_session("only", 0, case["session_duration_ms"], pressure_values=pressure),))

        result = evaluate_mean_mask_pressure_above_epap(night)

        self.assertEqual((result.status, result.reason_code, result.unit), (MetricStatus.CALCULATED, MetricReason.CALCULATED, "cm H₂O"))
        self.assertAlmostEqual(result.value, case["expected_value_cm_h2o"])
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.sample_cell_count, case["expected_sample_cell_count"])
        self.assertEqual(result.excluded_duration_ms, 0)

    def test_one_millisecond_below_minimum_is_insufficient_and_weights_partial_cell(self) -> None:
        case = self.fixture["cases"]["one_ms_below"]
        event = _event("last-ms", case["excluded_interval_ms"][0], 1)
        night = _night((_session("only", 0, case["session_duration_ms"], pressure_value=12.0, events=(event,)),))

        result = evaluate_mean_mask_pressure_above_epap(night)

        self.assertEqual((result.status, result.reason_code, result.value, result.unit), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.ELIGIBLE_DURATION_BELOW_300000_MS, None, None))
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.sample_cell_count, 7500)
        self.assertEqual([(value.start_time_ms, value.end_time_ms) for value in result.excluded_intervals], [tuple(case["excluded_interval_ms"])])

    def test_partial_sample_cell_uses_exact_positive_overlap_duration(self) -> None:
        case = self.fixture["cases"]["partial_sample_cell"]
        sample_count = case["session_duration_ms"] // 40
        pressure = (case["first_cell_pressure_cm_h2o"],) + (case["remaining_pressure_cm_h2o"],) * (sample_count - 1)
        excluded_start, excluded_end = case["excluded_interval_ms"]
        event = _event("partial-cell", excluded_start, excluded_end - excluded_start)
        night = _night((_session("only", 0, case["session_duration_ms"], pressure_values=pressure, events=(event,)),))

        result = evaluate_mean_mask_pressure_above_epap(night)

        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.sample_cell_count, case["expected_sample_cell_count"])
        self.assertAlmostEqual(result.value, case["expected_value_cm_h2o"])

    def test_overlapping_large_leak_and_artifact_are_unioned_without_double_counting(self) -> None:
        case = self.fixture["cases"]["overlapping_leak_and_artifact"]
        count = case["session_duration_ms"] // 40
        pressure = [12.0] * count
        pressure[3] = 16.0
        leak_start, leak_end = case["large_leak_interval_ms"]
        leak_updates = ((0, 5.0), (leak_start, 24.0), (leak_end, 5.0), (case["session_duration_ms"], 5.0))
        night = _night((_session("only", 0, case["session_duration_ms"], pressure_values=tuple(pressure), leak_updates=leak_updates),))

        result = evaluate_mean_mask_pressure_above_epap(night)

        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.sample_cell_count, case["expected_sample_cell_count"])
        self.assertEqual(result.value, case["expected_value_cm_h2o"])
        excluded = next(value for value in result.excluded_intervals if (value.start_time_ms, value.end_time_ms) == tuple(case["expected_excluded_interval_ms"]))
        self.assertEqual(set(excluded.reason_codes), {"isolated_impulse", "threshold_exceeded"})
        self.assertEqual(len(excluded.quality_finding_ids), 2)

    def test_signal_segments_and_gap_remain_independent(self) -> None:
        case = self.fixture["cases"]["segment_gap"]
        intervals = tuple(tuple(value) for value in case["segment_intervals_ms"])
        night = _night((_session("only", 0, case["session_duration_ms"], pressure_value=12.0, segment_intervals=intervals),))

        result = evaluate_mean_mask_pressure_above_epap(night)

        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.value, case["expected_value_cm_h2o"])
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(len(result.eligible_intervals), 2)
        self.assertTrue(all(len(value.source_segment_ids) == 3 for value in result.eligible_intervals))
        self.assertEqual([(value.start_time_ms, value.end_time_ms) for value in result.excluded_intervals], [tuple(case["expected_excluded_interval_ms"])])

    def test_split_sessions_pool_identical_settings_without_bridging_gap(self) -> None:
        case = self.fixture["cases"]["split_sessions"]
        (first_start, first_end), (second_start, second_end) = case["session_intervals_ms"]
        first = _session("first", first_start, first_end, pressure_value=11.0)
        second = _session("second", second_start, second_end, pressure_value=13.0)

        result = evaluate_mean_mask_pressure_above_epap(_night((second, first)))

        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(result.eligible_duration_ms, case["expected_eligible_duration_ms"])
        self.assertEqual(result.value, case["expected_value_cm_h2o"])
        self.assertEqual(len(result.eligible_intervals), 2)
        self.assertFalse(result.excluded_intervals)
        self.assertTrue(all(value.end_time_ms <= first_end or value.start_time_ms >= second_start for value in result.eligible_intervals))

    def test_split_sessions_with_different_settings_are_insufficient(self) -> None:
        first = _session("first", 0, 150_000, pressure_value=12.0)
        second = _session("second", 151_000, 301_000, pressure_value=12.0, ps_min=2.0)

        result = evaluate_mean_mask_pressure_above_epap(_night((first, second)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.SETTINGS_INCONSISTENT))
        self.assertEqual(result.eligible_duration_ms, 0)
        self.assertEqual(result.excluded_duration_ms, 300_000)

    def test_missing_settings_signals_and_unsupported_contracts_have_stable_reasons(self) -> None:
        complete = _session("only", 0, 300_000, pressure_value=12.0)
        missing_setting = replace(complete, settings=complete.settings[:-1])
        missing_signal = replace(complete, signals=tuple(signal for signal in complete.signals if signal.signal_kind != "flow_rate"))
        leak = next(signal for signal in complete.signals if signal.signal_kind == "leak_rate")
        unsupported_leak = replace(leak, value_semantics="total")
        unsupported = replace(complete, signals=tuple(unsupported_leak if signal.signal_kind == "leak_rate" else signal for signal in complete.signals))

        cases = (
            (missing_setting, MetricReason.SETTINGS_UNAVAILABLE),
            (missing_signal, MetricReason.REQUIRED_SIGNAL_UNAVAILABLE),
            (unsupported, MetricReason.UNSUPPORTED_SIGNAL_CONTRACT),
        )
        for session, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_mean_mask_pressure_above_epap(_night((session,)))
                self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, reason))

    def test_unresolved_artifact_input_has_no_silent_fallback(self) -> None:
        session = _session("only", 0, 300_000, pressure_value=12.0, include_gain=False)

        result = evaluate_mean_mask_pressure_above_epap(_night((session,)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.ELIGIBLE_DURATION_BELOW_300000_MS))
        self.assertTrue(any("artifact_input_missing" in value.reason_codes for value in result.excluded_intervals))

    def test_disjoint_required_signal_coverage_is_an_unresolved_quality_prerequisite(self) -> None:
        session = _session("only", 0, 300_000, pressure_value=12.0)
        flow = _waveform("only", "flow_rate", "L/min", ((0, 150_000),), (0.0,) * 3_750)
        pressure = _waveform("only", "mask_pressure", "cm H₂O", ((150_000, 300_000),), (12.0,) * 3_750)
        leak = next(signal for signal in session.signals if signal.signal_kind == "leak_rate")
        disjoint = replace(session, signals=(flow, pressure, leak))

        result = evaluate_mean_mask_pressure_above_epap(_night((disjoint,)))

        self.assertEqual((result.status, result.reason_code), (MetricStatus.INSUFFICIENT_EVIDENCE, MetricReason.QUALITY_PREREQUISITE_UNRESOLVED))
        self.assertEqual(result.eligible_duration_ms, 0)

    def test_missing_likely_wake_prerequisite_is_retained_but_does_not_exclude(self) -> None:
        result = evaluate_mean_mask_pressure_above_epap(_night((_session("only", 0, 300_000, pressure_value=12.0),)))

        wake_findings = [identifier for identifier in result.quality_finding_ids if identifier.startswith(f"quality:{QualityRule.LIKELY_WAKE_BREATHING.value}:")]
        self.assertEqual(result.status, MetricStatus.CALCULATED)
        self.assertEqual(len(wake_findings), 1)
        self.assertFalse(any(identifier in {finding for interval in result.excluded_intervals for finding in interval.quality_finding_ids} for identifier in wake_findings))
        self.assertTrue(any("does not establish sleep" in limitation for limitation in result.limitations))

    def test_result_is_deterministic_immutable_and_provenance_complete(self) -> None:
        night = _night((_session("only", 0, 300_000, pressure_value=12.0),))

        result = evaluate_mean_mask_pressure_above_epap(night)
        repeated = evaluate_mean_mask_pressure_above_epap(night)

        self.assertEqual(result, repeated)
        self.assertEqual(result.record_id, repeated.record_id)
        self.assertEqual(len(result.settings), 6)
        self.assertEqual(set(result.setting_record_ids), {value.setting_record_id for value in result.settings})
        self.assertTrue({"signal:only:flow_rate", "signal:only:mask_pressure", "signal:only:leak_rate"}.issubset(result.source_record_ids))
        self.assertTrue(result.quality_report_ids)
        self.assertTrue(result.quality_finding_ids)
        self.assertEqual(result.source_class, SourceClass.COMPANION_DERIVED)
        with self.assertRaises(FrozenInstanceError):
            result.value = 0.0  # type: ignore[misc]
        with self.assertRaises(MetricModelError):
            replace(result, reason_code=MetricReason.SETTINGS_UNAVAILABLE)


def _provenance(name: str, values: dict[str, object] | None = None) -> ProvenanceRecord:
    source_values = tuple(ProvenanceValue(key, json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)) for key, value in (values or {}).items())
    return ProvenanceRecord(
        record_id=f"provenance:{name}",
        source_classes=(SourceClass.MACHINE_RECORDED, SourceClass.OSCAR_NORMALIZED),
        source_system="synthetic_fixture",
        source_references=(SourceReference("fixture", name),),
        source_values=source_values,
    )


def _settings(suffix: str, *, epap: float = 10.0, ps_min: float = 1.0) -> tuple[SettingRecord, ...]:
    values = (
        ("therapy_mode_code", 6, None),
        ("loader_mode_code", 7, None),
        ("epap", epap, "cm H₂O"),
        ("ps_min", ps_min, "cm H₂O"),
        ("ps_max", 5.0, "cm H₂O"),
        ("max_ipap", epap + 5.0, "cm H₂O"),
    )
    return tuple(SettingRecord(f"setting:{suffix}:{name}", name, value, unit, _provenance(f"setting-{suffix}-{name}")) for name, value, unit in values)


def _waveform(suffix: str, kind: str, unit: str, intervals: tuple[tuple[int, int], ...], values: tuple[float, ...], *, include_gain: bool = True) -> SignalRecord:
    segments = []
    offset = 0
    for index, (start, end) in enumerate(intervals):
        count = (end - start) // 40
        segment_values = values[offset : offset + count]
        offset += count
        provenance_values = {"segment.offset": 0.0}
        if include_gain:
            provenance_values["segment.gain_per_raw_unit"] = 0.1
        segments.append(
            SignalSegmentRecord(
                f"segment:{suffix}:{kind}:{index}",
                start,
                end,
                IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                tuple(float(start + sample * 40) for sample in range(count)),
                segment_values,
                40.0,
                _provenance(f"segment-{suffix}-{kind}-{index}", provenance_values),
            )
        )
    if offset != len(values):
        raise AssertionError("The waveform fixture values do not match its segment durations.")
    return SignalRecord(f"signal:{suffix}:{kind}", kind, unit, SignalRepresentation.UNIFORM_WAVEFORM, tuple(segments), _provenance(f"signal-{suffix}-{kind}", {"signal.availability": "available"}))


def _leak(suffix: str, intervals: tuple[tuple[int, int], ...], updates: tuple[tuple[int, float], ...] | None = None) -> SignalRecord:
    segments = []
    if updates is not None:
        interval_updates = (updates,)
    else:
        interval_updates = tuple(((start, 5.0), (end, 5.0)) for start, end in intervals)
    for index, samples in enumerate(interval_updates):
        times = tuple(time for time, _ in samples)
        values = tuple(value for _, value in samples)
        segments.append(SignalSegmentRecord(f"segment:{suffix}:leak_rate:{index}", int(times[0]), int(times[-1]), IntervalClosure.START_AND_END_INCLUSIVE, times, values, None, _provenance(f"segment-{suffix}-leak-{index}", {"segment.gain_per_raw_unit": 0.1, "segment.offset": 0.0})))
    return SignalRecord(f"signal:{suffix}:leak_rate", "leak_rate", "L/min", SignalRepresentation.TIMED_UPDATES, tuple(segments), _provenance(f"signal-{suffix}-leak", {"signal.availability": "available"}), "unintentional")


def _event(suffix: str, start: int, duration: int) -> EventRecord:
    return EventRecord(f"event:{suffix}", "large_leak", start, duration, _provenance(f"event-{suffix}"))


def _session(
    suffix: str,
    start: int,
    end: int,
    *,
    pressure_value: float = 12.0,
    pressure_values: tuple[float, ...] | None = None,
    leak_updates: tuple[tuple[int, float], ...] | None = None,
    segment_intervals: tuple[tuple[int, int], ...] | None = None,
    events: tuple[EventRecord, ...] = (),
    ps_min: float = 1.0,
    include_gain: bool = True,
) -> SessionRecord:
    intervals = segment_intervals or ((start, end),)
    sample_count = sum((interval_end - interval_start) // 40 for interval_start, interval_end in intervals)
    pressure = pressure_values or (pressure_value,) * sample_count
    flow = (0.0,) * sample_count
    signals = (
        _waveform(suffix, "flow_rate", "L/min", intervals, flow, include_gain=include_gain),
        _waveform(suffix, "mask_pressure", "cm H₂O", intervals, pressure, include_gain=include_gain),
        _leak(suffix, intervals, leak_updates),
    )
    return SessionRecord(f"session:{suffix}", "device:fixture", start, end, _settings(suffix, ps_min=ps_min), events, signals, _provenance(f"session-{suffix}", {"events.completeness": "unknown"}))


def _night(sessions: tuple[SessionRecord, ...]) -> NightRecord:
    return NightRecord("night:fixture", "2026-09-02", "America/Denver", "12:00:00", sessions, _provenance("night"))


def _block_values(blocks: tuple[tuple[int, float], ...]) -> tuple[float, ...]:
    self_check = tuple(duration for duration, _ in blocks if duration % 40)
    if self_check:
        raise AssertionError("Each fixture pressure block must align to 40 ms cells.")
    return tuple(value for duration, value in blocks for _ in range(duration // 40))
