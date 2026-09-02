"""Deterministic version-1 minute-ventilation upper-tail ratio."""

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import math
from typing import Final, TypeAlias

from pap_pilot.engine.metrics.model import (
    MINIMUM_ELIGIBLE_DURATION_MS,
    MINIMUM_VENTILATION_OBSERVATIONS,
    MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION,
    VENTILATION_WINDOW_DURATION_MS,
    VENTILATION_WINDOW_STEP_MS,
    MetricId,
    MetricInterval,
    MetricModelError,
    MetricReason,
    MetricResult,
    MetricSettingValue,
    MetricStatus,
    MetricValue,
)
from pap_pilot.engine.model import IntervalClosure, NightRecord, SessionRecord, SignalRecord, SignalRepresentation, SignalSegmentRecord
from pap_pilot.engine.quality import QualityFinding, QualityImpact, QualityRule, QualityStatus, TimeBasis, evaluate_large_leak, evaluate_likely_wake_breathing, evaluate_signal_artifacts, evaluate_structural_quality


TimestampMs: TypeAlias = int | float
Interval: TypeAlias = tuple[TimestampMs, TimestampMs]

_REQUIRED_SETTINGS: Final = ("therapy_mode_code", "loader_mode_code", "epap", "ps_min", "ps_max", "max_ipap")
_REQUIRED_SIGNALS: Final = ("flow_rate", "leak_rate")
_PRESSURE_SETTINGS: Final = frozenset({"epap", "ps_min", "ps_max", "max_ipap"})
_LIMITATIONS: Final = (
    "The result describes eligible PAP-on time and does not establish sleep, awakenings, arousals, or sleep stage.",
    "This is an engineering estimate from positive Flow Rate, not the device's proprietary target minute ventilation, alveolar ventilation, spirometry, or a clinical measurement.",
    "The calculation does not correct for dead space, body size, mask or circuit dynamics, undetected wake, unrecognized source error, or expiratory volume.",
    "Overlapping one-minute windows are highly correlated; their count is evidence density, not an independent sample size for statistical inference.",
    "The ratio does not establish periodic breathing, hypocapnia, hyperventilation, an apnea type, causation by PS Min, or a favorable or safe outcome.",
)
_PARAMETERS: Final = (
    MetricValue("flow_sign_convention", "positive_inspiration"),
    MetricValue("minimum_eligible_duration_ms", MINIMUM_ELIGIBLE_DURATION_MS, "ms"),
    MetricValue("minimum_ventilation_observations", MINIMUM_VENTILATION_OBSERVATIONS, "count"),
    MetricValue("negative_flow_handling", "clamp_to_zero"),
    MetricValue("quantile_method", "Hyndman-Fan type 7"),
    MetricValue("quantile_probability_50", 0.50),
    MetricValue("quantile_probability_95", 0.95),
    MetricValue("required_sample_interval_ms", 40.0, "ms"),
    MetricValue("required_signal_kinds", ",".join(_REQUIRED_SIGNALS)),
    MetricValue("sample_cell_convention", "left_constant_start_inclusive_end_exclusive"),
    MetricValue("time_basis", TimeBasis.RAW_RELATIVE.value),
    MetricValue("ventilation_window_duration_ms", VENTILATION_WINDOW_DURATION_MS, "ms"),
    MetricValue("ventilation_window_step_ms", VENTILATION_WINDOW_STEP_MS, "ms"),
)


@dataclass(frozen=True, slots=True)
class _EligibleRun:
    session: SessionRecord
    flow_segment: SignalSegmentRecord
    leak_segment: SignalSegmentRecord
    start_time_ms: TimestampMs
    end_time_ms: TimestampMs


@dataclass(frozen=True, slots=True)
class _VentilationObservation:
    session_record_id: str
    flow_segment_id: str
    start_time_ms: TimestampMs
    end_time_ms: TimestampMs
    value_l_min: float


def evaluate_minute_ventilation_upper_tail_ratio(night: NightRecord) -> MetricResult:
    """Calculate metric-set v1 upper-tail ventilation dispersion for one night."""

    if not isinstance(night, NightRecord):
        raise MetricModelError("Minute-ventilation upper-tail ratio requires one NightRecord.")
    structural_report = evaluate_structural_quality(
        night,
        required_signal_kinds=_REQUIRED_SIGNALS,
        require_flow_pressure_alignment=False,
        time_basis=TimeBasis.RAW_RELATIVE,
    )
    signal_findings = tuple(
        finding
        for session in night.sessions
        for finding in (
            *evaluate_large_leak(session),
            *evaluate_signal_artifacts(session, "flow_rate"),
            *evaluate_likely_wake_breathing(session, None),
        )
    )
    findings = (*structural_report.findings, *signal_findings)
    requested = tuple(MetricInterval(session.record_id, session.start_time_ms, session.end_time_ms) for session in night.sessions)
    requested_duration = sum(value.end_time_ms - value.start_time_ms for value in requested)
    settings, setting_reason = _settings(night)
    contract_reason = _signal_contract_reason(night)
    quality_reason = _blocking_quality_reason(findings)
    blocking_reason = setting_reason or contract_reason or quality_reason
    if blocking_reason is not None:
        return _result(
            night=night,
            settings=settings,
            status=MetricStatus.INSUFFICIENT_EVIDENCE,
            reason=blocking_reason,
            value=None,
            measurements=(),
            requested=requested,
            eligible=(),
            excluded=_whole_scope_exclusions(night, findings, blocking_reason),
            requested_duration=requested_duration,
            eligible_duration=0,
            sample_cell_count=0,
            observation_count=0,
            structural_report_id=structural_report.record_id,
            signal_report_ids=(),
            findings=findings,
        )

    exclusions_by_session = _quality_exclusions(night, findings)
    eligible_runs = _eligible_runs(night, exclusions_by_session)
    eligible_intervals = tuple(
        MetricInterval(
            run.session.record_id,
            run.start_time_ms,
            run.end_time_ms,
            source_segment_ids=(run.flow_segment.record_id, run.leak_segment.record_id),
        )
        for run in eligible_runs
    )
    eligible_duration = math.fsum(value.end_time_ms - value.start_time_ms for value in eligible_intervals)
    excluded = _complement_intervals(night, eligible_intervals, exclusions_by_session)
    observations, sample_cell_count = _ventilation_observations(eligible_runs)
    if eligible_duration < MINIMUM_ELIGIBLE_DURATION_MS:
        return _result(
            night=night,
            settings=settings,
            status=MetricStatus.INSUFFICIENT_EVIDENCE,
            reason=MetricReason.ELIGIBLE_DURATION_BELOW_300000_MS,
            value=None,
            measurements=(),
            requested=requested,
            eligible=eligible_intervals,
            excluded=excluded,
            requested_duration=requested_duration,
            eligible_duration=eligible_duration,
            sample_cell_count=sample_cell_count,
            observation_count=len(observations),
            structural_report_id=structural_report.record_id,
            signal_report_ids=(),
            findings=findings,
        )
    if len(observations) < MINIMUM_VENTILATION_OBSERVATIONS:
        return _result(
            night=night,
            settings=settings,
            status=MetricStatus.INSUFFICIENT_EVIDENCE,
            reason=MetricReason.TOO_FEW_VENTILATION_WINDOWS,
            value=None,
            measurements=(),
            requested=requested,
            eligible=eligible_intervals,
            excluded=excluded,
            requested_duration=requested_duration,
            eligible_duration=eligible_duration,
            sample_cell_count=sample_cell_count,
            observation_count=len(observations),
            structural_report_id=structural_report.record_id,
            signal_report_ids=(),
            findings=findings,
        )

    values = tuple(observation.value_l_min for observation in observations)
    q50 = _type_7_quantile(values, 0.50)
    q95 = _type_7_quantile(values, 0.95)
    measurements = (MetricValue("ventilation_q50_l_min", q50, "L/min"), MetricValue("ventilation_q95_l_min", q95, "L/min"))
    if not math.isfinite(q50) or q50 <= 0:
        return _result(
            night=night,
            settings=settings,
            status=MetricStatus.INSUFFICIENT_EVIDENCE,
            reason=MetricReason.NONPOSITIVE_VENTILATION_MEDIAN,
            value=None,
            measurements=measurements,
            requested=requested,
            eligible=eligible_intervals,
            excluded=excluded,
            requested_duration=requested_duration,
            eligible_duration=eligible_duration,
            sample_cell_count=sample_cell_count,
            observation_count=len(observations),
            structural_report_id=structural_report.record_id,
            signal_report_ids=(),
            findings=findings,
        )
    return _result(
        night=night,
        settings=settings,
        status=MetricStatus.CALCULATED,
        reason=MetricReason.CALCULATED,
        value=q95 / q50,
        measurements=measurements,
        requested=requested,
        eligible=eligible_intervals,
        excluded=excluded,
        requested_duration=requested_duration,
        eligible_duration=eligible_duration,
        sample_cell_count=sample_cell_count,
        observation_count=len(observations),
        structural_report_id=structural_report.record_id,
        signal_report_ids=(),
        findings=findings,
    )


def _settings(night: NightRecord) -> tuple[tuple[MetricSettingValue, ...], MetricReason | None]:
    snapshots: list[MetricSettingValue] = []
    signatures = []
    for session in night.sessions:
        by_name = {setting.name: setting for setting in session.settings}
        if any(name not in by_name for name in _REQUIRED_SETTINGS):
            return tuple(snapshots), MetricReason.SETTINGS_UNAVAILABLE
        values = []
        for name in _REQUIRED_SETTINGS:
            setting = by_name[name]
            expected_unit = "cm H₂O" if name in _PRESSURE_SETTINGS else None
            if not _finite_number(setting.value) or setting.unit != expected_unit:
                return tuple(snapshots), MetricReason.SETTINGS_UNAVAILABLE
            if name in {"therapy_mode_code", "loader_mode_code"} and type(setting.value) is not int:
                return tuple(snapshots), MetricReason.SETTINGS_UNAVAILABLE
            snapshots.append(MetricSettingValue(session.record_id, setting.record_id, name, setting.value, setting.unit))
            values.append(setting.value)
        therapy_mode, loader_mode, epap, ps_min, ps_max, max_ipap = values
        if therapy_mode != 6 or loader_mode != 7 or ps_min > ps_max or not math.isclose(epap + ps_max, max_ipap, rel_tol=1e-9, abs_tol=1e-9):
            return tuple(snapshots), MetricReason.SETTINGS_UNAVAILABLE
        signatures.append(tuple(values))
    if any(signature != signatures[0] for signature in signatures[1:]):
        return tuple(snapshots), MetricReason.SETTINGS_INCONSISTENT
    return tuple(snapshots), None


def _signal_contract_reason(night: NightRecord) -> MetricReason | None:
    for session in night.sessions:
        signals = {signal.signal_kind: signal for signal in session.signals}
        if any(kind not in signals or not signals[kind].segments for kind in _REQUIRED_SIGNALS):
            return MetricReason.REQUIRED_SIGNAL_UNAVAILABLE
        flow, leak = (signals[kind] for kind in _REQUIRED_SIGNALS)
        if (flow.representation, flow.unit) != (SignalRepresentation.UNIFORM_WAVEFORM, "L/min"):
            return MetricReason.UNSUPPORTED_SIGNAL_CONTRACT
        if (leak.representation, leak.unit, leak.value_semantics) != (SignalRepresentation.TIMED_UPDATES, "L/min", "unintentional"):
            return MetricReason.UNSUPPORTED_SIGNAL_CONTRACT
        if any(segment.interval_closure is not IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE or segment.sample_interval_ms != 40.0 for segment in flow.segments):
            return MetricReason.UNSUPPORTED_SIGNAL_CONTRACT
        if _segments_overlap(flow) or _segments_overlap(leak):
            return MetricReason.UNSUPPORTED_SIGNAL_CONTRACT
        if not any(following > current for segment in leak.segments for current, following in zip(segment.sample_times_ms, segment.sample_times_ms[1:])):
            return MetricReason.REQUIRED_SIGNAL_UNAVAILABLE
    return None


def _segments_overlap(signal: SignalRecord) -> bool:
    return any(current.end_time_ms > following.start_time_ms for current, following in zip(signal.segments, signal.segments[1:]))


def _is_flow_artifact(finding: QualityFinding) -> bool:
    return finding.rule_id is QualityRule.SIGNAL_ARTIFACT and any(value.name == "signal_kind" and value.value == "flow_rate" for value in finding.parameters)


def _is_required_finding(finding: QualityFinding) -> bool:
    return finding.rule_id in {QualityRule.MISSING_REQUIRED_SIGNAL, QualityRule.LARGE_LEAK} or _is_flow_artifact(finding)


def _blocking_quality_reason(findings: tuple[QualityFinding, ...]) -> MetricReason | None:
    blockers = tuple(finding for finding in findings if _is_required_finding(finding) and finding.status is QualityStatus.INSUFFICIENT_EVIDENCE and finding.impact is QualityImpact.BLOCK_REQUESTED_ANALYSIS)
    if not blockers:
        return None
    if any(finding.reason_code in {"channel_missing", "data_missing", "leak_evidence_missing"} for finding in blockers):
        return MetricReason.REQUIRED_SIGNAL_UNAVAILABLE
    if any(finding.reason_code in {"unsupported_signal_contract", "unsupported_leak_contract"} for finding in blockers):
        return MetricReason.UNSUPPORTED_SIGNAL_CONTRACT
    return MetricReason.QUALITY_PREREQUISITE_UNRESOLVED


def _quality_exclusions(night: NightRecord, findings: tuple[QualityFinding, ...]) -> dict[str, tuple[MetricInterval, ...]]:
    by_session = {}
    for session in night.sessions:
        intervals = []
        for finding in findings:
            if not _is_required_finding(finding) or finding.impact is not QualityImpact.EXCLUDE_INTERVAL or session.record_id not in finding.source_record_ids or finding.start_time_ms is None or finding.end_time_ms is None:
                continue
            start = max(session.start_time_ms, finding.start_time_ms)
            end = min(session.end_time_ms, finding.end_time_ms)
            if start < end:
                intervals.append(MetricInterval(session.record_id, start, end, quality_finding_ids=(finding.record_id,), reason_codes=(finding.reason_code,)))
        by_session[session.record_id] = _union_exclusions(intervals)
    return by_session


def _union_exclusions(intervals: list[MetricInterval]) -> tuple[MetricInterval, ...]:
    if not intervals:
        return ()
    ordered = sorted(intervals, key=lambda value: (value.start_time_ms, value.end_time_ms))
    result = [ordered[0]]
    for interval in ordered[1:]:
        previous = result[-1]
        if interval.start_time_ms > previous.end_time_ms:
            result.append(interval)
            continue
        result[-1] = MetricInterval(
            previous.session_record_id,
            previous.start_time_ms,
            max(previous.end_time_ms, interval.end_time_ms),
            quality_finding_ids=tuple(sorted(set(previous.quality_finding_ids + interval.quality_finding_ids))),
            reason_codes=tuple(sorted(set(previous.reason_codes + interval.reason_codes))),
        )
    return tuple(result)


def _eligible_runs(night: NightRecord, exclusions: dict[str, tuple[MetricInterval, ...]]) -> tuple[_EligibleRun, ...]:
    runs = []
    for session in night.sessions:
        signals = {signal.signal_kind: signal for signal in session.signals}
        flow = signals["flow_rate"]
        leak = signals["leak_rate"]
        for flow_segment in flow.segments:
            for leak_segment in leak.segments:
                leak_intervals = tuple((current, following) for current, following in zip(leak_segment.sample_times_ms, leak_segment.sample_times_ms[1:]) if current < following)
                for leak_start, leak_end in _merge_intervals(leak_intervals):
                    start = max(session.start_time_ms, flow_segment.start_time_ms, leak_start)
                    end = min(session.end_time_ms, flow_segment.end_time_ms, leak_end)
                    if start >= end:
                        continue
                    for eligible_start, eligible_end in _subtract((start, end), exclusions[session.record_id]):
                        runs.append(_EligibleRun(session, flow_segment, leak_segment, eligible_start, eligible_end))
    return tuple(runs)


def _ventilation_observations(runs: tuple[_EligibleRun, ...]) -> tuple[tuple[_VentilationObservation, ...], int]:
    observations = []
    cells = set()
    integral_cache = {}
    for run in runs:
        if run.end_time_ms - run.start_time_ms < VENTILATION_WINDOW_DURATION_MS:
            continue
        segment = run.flow_segment
        integral = integral_cache.setdefault(segment.record_id, _positive_flow_integral(segment))
        anchor = run.start_time_ms + VENTILATION_WINDOW_DURATION_MS
        last_anchor = None
        while anchor <= run.end_time_ms:
            window_start = anchor - VENTILATION_WINDOW_DURATION_MS
            volume = _integral_at(segment, integral, anchor) - _integral_at(segment, integral, window_start)
            observations.append(_VentilationObservation(run.session.record_id, segment.record_id, window_start, anchor, volume / VENTILATION_WINDOW_DURATION_MS))
            last_anchor = anchor
            anchor += VENTILATION_WINDOW_STEP_MS
        assert last_anchor is not None
        for index, sample_time in enumerate(segment.sample_times_ms):
            sample_end = segment.sample_times_ms[index + 1] if index + 1 < len(segment.sample_times_ms) else segment.end_time_ms
            if sample_time < last_anchor and sample_end > run.start_time_ms:
                cells.add((run.session.record_id, segment.record_id, index))
    return tuple(observations), len(cells)


def _positive_flow_integral(segment: SignalSegmentRecord) -> tuple[float, ...]:
    prefix = [0.0]
    for index, (sample_time, value) in enumerate(zip(segment.sample_times_ms, segment.values)):
        sample_end = segment.sample_times_ms[index + 1] if index + 1 < len(segment.sample_times_ms) else segment.end_time_ms
        prefix.append(prefix[-1] + max(value, 0.0) * (sample_end - sample_time))
    return tuple(prefix)


def _integral_at(segment: SignalSegmentRecord, prefix: tuple[float, ...], timestamp: TimestampMs) -> float:
    if timestamp <= segment.start_time_ms:
        return 0.0
    if timestamp >= segment.end_time_ms:
        return prefix[-1]
    index = bisect_right(segment.sample_times_ms, timestamp) - 1
    return prefix[index] + max(segment.values[index], 0.0) * (timestamp - segment.sample_times_ms[index])


def _type_7_quantile(values: tuple[float, ...], probability: float) -> float:
    ordered = tuple(sorted(values))
    h = 1 + (len(ordered) - 1) * probability
    j = math.floor(h)
    if j == len(ordered):
        return float(ordered[-1])
    g = h - j
    return float(ordered[j - 1] + g * (ordered[j] - ordered[j - 1]))


def _complement_intervals(night: NightRecord, eligible: tuple[MetricInterval, ...], exclusions: dict[str, tuple[MetricInterval, ...]]) -> tuple[MetricInterval, ...]:
    result = []
    for session in night.sessions:
        covered = _merge_intervals((value.start_time_ms, value.end_time_ms) for value in eligible if value.session_record_id == session.record_id)
        for start, end in _subtract((session.start_time_ms, session.end_time_ms), covered):
            related = tuple(value for value in exclusions[session.record_id] if value.start_time_ms < end and value.end_time_ms > start)
            result.append(
                MetricInterval(
                    session.record_id,
                    start,
                    end,
                    quality_finding_ids=tuple(sorted({identifier for value in related for identifier in value.quality_finding_ids})),
                    reason_codes=tuple(sorted({reason for value in related for reason in value.reason_codes})) or ("outside_required_signal_intersection",),
                )
            )
    return tuple(result)


def _whole_scope_exclusions(night: NightRecord, findings: tuple[QualityFinding, ...], reason: MetricReason) -> tuple[MetricInterval, ...]:
    blockers = tuple(finding.record_id for finding in findings if _is_required_finding(finding) and finding.status is QualityStatus.INSUFFICIENT_EVIDENCE and finding.impact is QualityImpact.BLOCK_REQUESTED_ANALYSIS)
    return tuple(MetricInterval(session.record_id, session.start_time_ms, session.end_time_ms, quality_finding_ids=tuple(sorted(blockers)), reason_codes=(reason.value,)) for session in night.sessions)


def _result(
    *,
    night: NightRecord,
    settings: tuple[MetricSettingValue, ...],
    status: MetricStatus,
    reason: MetricReason,
    value: float | None,
    measurements: tuple[MetricValue, ...],
    requested: tuple[MetricInterval, ...],
    eligible: tuple[MetricInterval, ...],
    excluded: tuple[MetricInterval, ...],
    requested_duration: TimestampMs,
    eligible_duration: TimestampMs,
    sample_cell_count: int,
    observation_count: int,
    structural_report_id: str,
    signal_report_ids: tuple[str, ...],
    findings: tuple[QualityFinding, ...],
) -> MetricResult:
    used_segment_ids = {identifier for interval in eligible for identifier in interval.source_segment_ids}
    source_records = {night.record_id, *(session.record_id for session in night.sessions), *(setting.setting_record_id for setting in settings)}
    source_provenance = {night.provenance.record_id, *(session.provenance.record_id for session in night.sessions)}
    source_records.update(identifier for finding in findings for identifier in finding.source_record_ids)
    source_provenance.update(identifier for finding in findings for identifier in finding.source_provenance_ids)
    for session in night.sessions:
        for setting in session.settings:
            if setting.record_id in source_records:
                source_provenance.add(setting.provenance.record_id)
        for signal in session.signals:
            used = tuple(segment for segment in signal.segments if segment.record_id in used_segment_ids)
            if not used:
                continue
            source_records.add(signal.record_id)
            source_records.update(segment.record_id for segment in used)
            source_provenance.add(signal.provenance.record_id)
            source_provenance.update(segment.provenance.record_id for segment in used)
    quality_finding_ids = tuple(sorted(finding.record_id for finding in findings))
    quality_report_ids = tuple(sorted((structural_report_id, *signal_report_ids)))
    excluded_duration = requested_duration - eligible_duration
    identity = (
        MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO.value,
        MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION,
        night.record_id,
        status.value,
        reason.value,
        value,
        measurements,
        settings,
        eligible,
        excluded,
        tuple(sorted(source_records)),
        tuple(sorted(source_provenance)),
        quality_report_ids,
        quality_finding_ids,
        eligible_duration,
        sample_cell_count,
        observation_count,
    )
    return MetricResult(
        record_id=f"metric:minute-ventilation-upper-tail-ratio:{hashlib.sha256(repr(identity).encode()).hexdigest()[:20]}",
        metric_id=MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO,
        algorithm_version=MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION,
        status=status,
        reason_code=reason,
        value=value,
        unit="1" if status is MetricStatus.CALCULATED else None,
        parameters=_PARAMETERS,
        settings=settings,
        night_record_id=night.record_id,
        session_record_ids=tuple(session.record_id for session in night.sessions),
        setting_record_ids=tuple(setting.setting_record_id for setting in settings),
        source_record_ids=tuple(source_records),
        source_provenance_ids=tuple(source_provenance),
        quality_report_ids=quality_report_ids,
        quality_finding_ids=quality_finding_ids,
        requested_intervals=requested,
        eligible_intervals=eligible,
        excluded_intervals=excluded,
        requested_duration_ms=requested_duration,
        eligible_duration_ms=eligible_duration,
        excluded_duration_ms=excluded_duration,
        sample_cell_count=sample_cell_count,
        limitations=_LIMITATIONS,
        measurements=measurements,
        observation_count=observation_count,
    )


def _merge_intervals(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    ordered = sorted(intervals)
    merged = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)


def _subtract(scope: Interval, exclusions: tuple[MetricInterval, ...] | tuple[Interval, ...]) -> tuple[Interval, ...]:
    cursor = scope[0]
    result = []
    for value in exclusions:
        start, end = (value.start_time_ms, value.end_time_ms) if isinstance(value, MetricInterval) else value
        if end <= cursor or start >= scope[1]:
            continue
        if start > cursor:
            result.append((cursor, min(start, scope[1])))
        cursor = max(cursor, end)
        if cursor >= scope[1]:
            break
    if cursor < scope[1]:
        result.append((cursor, scope[1]))
    return tuple(result)


def _finite_number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(float(value))
    except OverflowError:
        return False
