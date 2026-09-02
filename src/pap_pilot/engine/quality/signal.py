"""Deterministic version-1 signal quality rules for normalized PAP records."""

from collections.abc import Iterable
import hashlib
import json
import math
from typing import Final, TypeAlias

from pap_pilot.engine.model import EventRecord, SessionRecord, SignalRecord, SignalRepresentation, SignalSegmentRecord
from pap_pilot.engine.quality.model import (
    ARTIFACT_SAMPLE_INTERVAL_MS,
    ARTIFACT_RAW_COUNT_ABS_TOLERANCE,
    FLOW_IMPULSE_THRESHOLD_L_MIN,
    FLOW_NEIGHBOR_TOLERANCE_L_MIN,
    LARGE_LEAK_THRESHOLD_L_MIN,
    PRESSURE_IMPULSE_THRESHOLD_CM_H2O,
    PRESSURE_NEIGHBOR_TOLERANCE_CM_H2O,
    WAKE_AMPLITUDE_CV_THRESHOLD,
    WAKE_DURATION_CV_THRESHOLD,
    WAKE_MINIMUM_ELIGIBLE_BREATHS,
    WAKE_REQUIRED_IRREGULAR_WINDOWS,
    WAKE_WINDOW_BREATHS,
    QualityFinding,
    QualityImpact,
    QualityModelError,
    QualityRule,
    QualityStatus,
    QualityValue,
    SignalQualityReport,
    ValidatedBreath,
    ValidatedBreathSeries,
)
from pap_pilot.engine.quality.structural import (
    _clip,
    _finding,
    _merge,
    _requested_interval,
    _signal_sources,
    evaluate_missing_required_signals,
)


TimestampMs: TypeAlias = int | float
Interval: TypeAlias = tuple[TimestampMs, TimestampMs]

_LEAK_LIMITATION: Final = "Large-leak findings apply only to the mapped ResMed unintentional Leak contract; sparse final values are not extended past their stored point."
_ARTIFACT_LIMITATION: Final = "Artifact findings are conservative engineering heuristics for automated morphology and do not prove that the physiological signal is false."
_WAKE_LIMITATION: Final = "Likely wake breathing is a provisional flow-irregularity candidate, not confirmed wake, arousal, sleep stage, or a diagnosis."
_FLOW_CONTRACT: Final = (SignalRepresentation.UNIFORM_WAVEFORM, "L/min")
_PRESSURE_CONTRACT: Final = (SignalRepresentation.UNIFORM_WAVEFORM, "cm H₂O")
_LEAK_CONTRACT: Final = (SignalRepresentation.TIMED_UPDATES, "L/min", "unintentional")
_RESPIRATORY_EVENT_KINDS: Final = frozenset({"obstructive_apnea", "clear_airway_apnea", "unclassified_apnea", "hypopnea", "rera"})


def evaluate_large_leak(
    session: SessionRecord,
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> tuple[QualityFinding, ...]:
    """Evaluate sparse unintentional Leak and observed machine Large Leak spans."""

    start, end = _requested_interval(session, start_time_ms, end_time_ms)
    parameters = (
        QualityValue("large_leak_threshold_l_min", LARGE_LEAK_THRESHOLD_L_MIN, "L/min"),
        QualityValue("requested_end_time_ms", end, "ms"),
        QualityValue("requested_start_time_ms", start, "ms"),
        QualityValue("threshold_comparison", "greater_than_or_equal"),
    )
    findings: list[QualityFinding] = []
    machine_findings = _machine_large_leak_findings(session, start, end, parameters)
    findings.extend(machine_findings)
    leak = next((signal for signal in session.signals if signal.signal_kind == "leak_rate"), None)
    if leak is None:
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.INSUFFICIENT_EVIDENCE,
                impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                reason="leak_evidence_missing",
                evaluated_record_id=session.record_id,
                records=(session.record_id,),
                provenance=(session.provenance.record_id,),
                parameters=parameters,
                measurements=(QualityValue("leak_signal_present", False),),
                limitations=(_LEAK_LIMITATION,),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier="channel-missing",
            )
        )
        return tuple(findings)

    records, provenance = _signal_sources(session, leak)
    if (leak.representation, leak.unit, leak.value_semantics) != _LEAK_CONTRACT:
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.INSUFFICIENT_EVIDENCE,
                impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                reason="unsupported_leak_contract",
                evaluated_record_id=leak.record_id,
                records=records,
                provenance=provenance,
                parameters=parameters,
                measurements=(
                    QualityValue("observed_representation", leak.representation.value),
                    QualityValue("observed_semantics", leak.value_semantics),
                    QualityValue("observed_unit", leak.unit),
                ),
                limitations=(_LEAK_LIMITATION,),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier="unsupported-contract",
            )
        )
        return tuple(findings)

    coverage = evaluate_missing_required_signals(session, ("leak_rate",), start_time_ms=start, end_time_ms=end)
    coverage_complete = True
    for coverage_finding in coverage:
        if coverage_finding.status is QualityStatus.PASS:
            continue
        coverage_complete = False
        reason = "unsupported_leak_contract" if coverage_finding.reason_code == "unsupported_signal_contract" else "leak_evidence_missing"
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.INSUFFICIENT_EVIDENCE,
                impact=QualityImpact.EXCLUDE_INTERVAL if coverage_finding.start_time_ms is not None else QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                reason=reason,
                evaluated_record_id=leak.record_id,
                records=coverage_finding.source_record_ids,
                provenance=coverage_finding.source_provenance_ids,
                parameters=parameters,
                measurements=coverage_finding.measurements,
                limitations=(_LEAK_LIMITATION,),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier=f"coverage:{coverage_finding.record_id}",
                interval=_finding_interval(coverage_finding),
            )
        )

    threshold_intervals = _threshold_leak_intervals(leak, start, end)
    for interval_start, interval_end in threshold_intervals:
        peak = _peak_sparse_value(leak, interval_start, interval_end)
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.FLAGGED,
                impact=QualityImpact.EXCLUDE_INTERVAL,
                reason="threshold_exceeded",
                evaluated_record_id=leak.record_id,
                records=records,
                provenance=provenance,
                parameters=parameters,
                measurements=(
                    QualityValue("interval_duration_ms", interval_end - interval_start, "ms"),
                    QualityValue("peak_observed_leak_l_min", peak, "L/min"),
                ),
                limitations=(_LEAK_LIMITATION,),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier=f"threshold:{interval_start}:{interval_end}",
                interval=(interval_start, interval_end),
            )
        )

    findings.extend(_final_leak_point_findings(session, leak, start, end, parameters, records, provenance))

    if not findings and coverage_complete:
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.PASS,
                impact=QualityImpact.NONE,
                reason="condition_not_observed",
                evaluated_record_id=leak.record_id,
                records=records,
                provenance=provenance,
                parameters=parameters,
                measurements=(QualityValue("maximum_observed_leak_l_min", _maximum_sparse_evidence(leak, start, end), "L/min"),),
                limitations=(_LEAK_LIMITATION, "This pass is threshold-based; absence of a machine Large Leak event is not treated as proof of complete event evidence."),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier="threshold-pass",
            )
        )
    return tuple(findings)


def evaluate_signal_artifacts(
    session: SessionRecord,
    signal_kind: str,
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> tuple[QualityFinding, ...]:
    """Evaluate digital clipping and isolated impulses in one waveform signal."""

    if type(signal_kind) is not str or not signal_kind.strip():
        raise QualityModelError("The artifact signal kind must be nonempty text.")
    start, end = _requested_interval(session, start_time_ms, end_time_ms)
    contract = {
        "flow_rate": (_FLOW_CONTRACT, FLOW_IMPULSE_THRESHOLD_L_MIN, FLOW_NEIGHBOR_TOLERANCE_L_MIN, "L/min"),
        "mask_pressure": (_PRESSURE_CONTRACT, PRESSURE_IMPULSE_THRESHOLD_CM_H2O, PRESSURE_NEIGHBOR_TOLERANCE_CM_H2O, "cm H₂O"),
    }.get(signal_kind)
    if contract is None:
        return (
            _finding(
                rule=QualityRule.SIGNAL_ARTIFACT,
                status=QualityStatus.NOT_APPLICABLE,
                impact=QualityImpact.NONE,
                reason="rule_not_applicable",
                evaluated_record_id=session.record_id,
                records=(session.record_id,),
                provenance=(session.provenance.record_id,),
                parameters=(QualityValue("signal_kind", signal_kind),),
                measurements=(),
                limitations=(_ARTIFACT_LIMITATION,),
                capabilities=("waveform_morphology",),
                qualifier=f"{signal_kind}:not-applicable",
            ),
        )
    expected_contract, impulse_threshold, neighbor_tolerance, unit = contract
    parameters = (
        QualityValue("expected_sample_interval_ms", ARTIFACT_SAMPLE_INTERVAL_MS, "ms"),
        QualityValue("impulse_threshold", impulse_threshold, unit),
        QualityValue("neighbor_tolerance", neighbor_tolerance, unit),
        QualityValue("signal_kind", signal_kind),
    )
    signal = next((value for value in session.signals if value.signal_kind == signal_kind), None)
    if signal is None or (signal.representation, signal.unit) != expected_contract or not signal.segments:
        records = (session.record_id,) if signal is None else _signal_sources(session, signal)[0]
        provenance = (session.provenance.record_id,) if signal is None else _signal_sources(session, signal)[1]
        return (
            _finding(
                rule=QualityRule.SIGNAL_ARTIFACT,
                status=QualityStatus.INSUFFICIENT_EVIDENCE,
                impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                reason="artifact_input_missing",
                evaluated_record_id=session.record_id if signal is None else signal.record_id,
                records=records,
                provenance=provenance,
                parameters=parameters,
                measurements=(QualityValue("compatible_signal_present", False),),
                limitations=(_ARTIFACT_LIMITATION,),
                capabilities=("waveform_morphology",),
                qualifier=f"{signal_kind}:signal-unavailable",
            ),
        )

    findings: list[QualityFinding] = []
    for segment in signal.segments:
        clipped = _clip((segment.start_time_ms, segment.end_time_ms), start, end)
        if clipped is None:
            continue
        segment_records = (session.record_id, signal.record_id, segment.record_id)
        segment_provenance = (session.provenance.record_id, signal.provenance.record_id, segment.provenance.record_id)
        if segment.sample_interval_ms != ARTIFACT_SAMPLE_INTERVAL_MS:
            findings.append(
                _artifact_insufficient(segment, segment_records, segment_provenance, parameters, signal_kind, "waveform_contract", clipped)
            )
            continue
        findings.extend(
            _digital_clipping_findings(segment, segment_records, segment_provenance, parameters, signal_kind, unit, start, end)
        )
        findings.extend(
            _isolated_impulse_findings(
                segment,
                segment_records,
                segment_provenance,
                parameters,
                signal_kind,
                impulse_threshold,
                neighbor_tolerance,
                unit,
                start,
                end,
            )
        )
    if not findings:
        records, provenance = _signal_sources(session, signal)
        findings.append(
            _finding(
                rule=QualityRule.SIGNAL_ARTIFACT,
                status=QualityStatus.INSUFFICIENT_EVIDENCE,
                impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                reason="artifact_input_missing",
                evaluated_record_id=signal.record_id,
                records=records,
                provenance=provenance,
                parameters=parameters,
                measurements=(QualityValue("overlapping_segment_count", 0, "count"),),
                limitations=(_ARTIFACT_LIMITATION,),
                capabilities=("waveform_morphology",),
                qualifier=f"{signal_kind}:no-overlap",
            )
        )
    return tuple(findings)


def evaluate_likely_wake_breathing(
    session: SessionRecord,
    breath_series: ValidatedBreathSeries | None,
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> tuple[QualityFinding, ...]:
    """Evaluate the version-1 irregular-breathing candidate on eligible breaths."""

    start, end = _requested_interval(session, start_time_ms, end_time_ms)
    base_parameters = (
        QualityValue("amplitude_cv_threshold", WAKE_AMPLITUDE_CV_THRESHOLD),
        QualityValue("duration_cv_threshold", WAKE_DURATION_CV_THRESHOLD),
        QualityValue("minimum_eligible_breaths", WAKE_MINIMUM_ELIGIBLE_BREATHS, "count"),
        QualityValue("required_consecutive_irregular_windows", WAKE_REQUIRED_IRREGULAR_WINDOWS, "count"),
        QualityValue("window_breaths", WAKE_WINDOW_BREATHS, "count"),
    )
    flow = next((signal for signal in session.signals if signal.signal_kind == "flow_rate"), None)
    if breath_series is None:
        return (
            _wake_insufficient(
                session,
                records=(session.record_id,) if flow is None else _signal_sources(session, flow)[0],
                provenance=(session.provenance.record_id,) if flow is None else _signal_sources(session, flow)[1],
                parameters=base_parameters,
                reason="wake_prerequisite_missing",
                qualifier="validated-breath-series-missing",
                measurements=(QualityValue("validated_breath_series_present", False),),
            ),
        )
    if not isinstance(breath_series, ValidatedBreathSeries):
        raise QualityModelError("Likely-wake analysis requires a ValidatedBreathSeries or null.")
    if flow is None or (flow.representation, flow.unit) != _FLOW_CONTRACT:
        return (
            _wake_insufficient(
                session,
                records=(session.record_id, breath_series.record_id, *breath_series.source_record_ids),
                provenance=(session.provenance.record_id, *breath_series.source_provenance_ids),
                parameters=base_parameters,
                reason="wake_prerequisite_missing",
                qualifier="flow-unavailable",
                measurements=(QualityValue("compatible_flow_present", False),),
            ),
        )
    if breath_series.session_record_id != session.record_id or breath_series.flow_signal_record_id != flow.record_id:
        raise QualityModelError("Validated breath-series identity does not match the evaluated session and Flow Rate signal.")
    if any(breath.start_time_ms < session.start_time_ms or breath.end_time_ms > session.end_time_ms for breath in breath_series.breaths):
        raise QualityModelError("Validated breaths must be contained in the evaluated session.")

    parameters = base_parameters + (
        QualityValue("breath_detector_id", breath_series.detector_id),
        QualityValue("breath_detector_version", breath_series.detector_version),
    )
    respiratory_events = tuple(event for event in session.events if event.event_kind in _RESPIRATORY_EVENT_KINDS)
    records = (
        session.record_id,
        flow.record_id,
        breath_series.record_id,
        *(breath.record_id for breath in breath_series.breaths),
        *(event.record_id for event in respiratory_events),
        *breath_series.source_record_ids,
    )
    provenance = (
        session.provenance.record_id,
        flow.provenance.record_id,
        *(event.provenance.record_id for event in respiratory_events),
        *breath_series.source_provenance_ids,
    )
    prerequisite_findings = (
        *evaluate_missing_required_signals(session, ("flow_rate", "leak_rate"), start_time_ms=start, end_time_ms=end),
        *evaluate_large_leak(session, start_time_ms=start, end_time_ms=end),
        *evaluate_signal_artifacts(session, "flow_rate", start_time_ms=start, end_time_ms=end),
    )
    records = (*records, *(record_id for finding in prerequisite_findings for record_id in finding.source_record_ids))
    provenance = (*provenance, *(record_id for finding in prerequisite_findings for record_id in finding.source_provenance_ids))
    blocking_whole_scope = [finding for finding in prerequisite_findings if _is_wake_prerequisite_failure(finding, flow) and finding.start_time_ms is None]
    if blocking_whole_scope:
        return (
            _wake_insufficient(
                session,
                records=records,
                provenance=provenance,
                parameters=parameters,
                reason="wake_prerequisite_missing",
                qualifier="whole-scope-prerequisite",
                measurements=(QualityValue("blocking_prerequisite_count", len(blocking_whole_scope), "count"),),
            ),
        )

    blocked_intervals = _merge(
        (finding.start_time_ms, finding.end_time_ms)
        for finding in prerequisite_findings
        if _is_wake_prerequisite_failure(finding, flow) and finding.start_time_ms is not None and finding.end_time_ms is not None
    )
    findings = [
        _wake_insufficient(
            session,
            records=records,
            provenance=provenance,
            parameters=parameters,
            reason="wake_prerequisite_missing",
            qualifier=f"blocked:{interval_start}:{interval_end}",
            measurements=(QualityValue("blocked_duration_ms", interval_end - interval_start, "ms"),),
            interval=(interval_start, interval_end),
        )
        for interval_start, interval_end in blocked_intervals
    ]
    breaths = tuple(
        breath
        for breath in breath_series.breaths
        if breath.start_time_ms >= start and breath.end_time_ms <= end
    )
    suppressed = _suppressed_breath_indexes(breaths, session.events)
    eligible = tuple(
        index
        for index, breath in enumerate(breaths)
        if index not in suppressed and not any(_overlaps((breath.start_time_ms, breath.end_time_ms), interval) for interval in blocked_intervals)
    )
    runs = _consecutive_breath_runs(breaths, eligible)
    evaluable_runs = tuple(run for run in runs if len(run) >= WAKE_MINIMUM_ELIGIBLE_BREATHS)
    if not evaluable_runs:
        findings.append(
            _wake_insufficient(
                session,
                records=records,
                provenance=provenance,
                parameters=parameters,
                reason="too_few_eligible_breaths",
                qualifier="eligible-breath-count",
                measurements=(
                    QualityValue("eligible_breath_count", len(eligible), "count"),
                    QualityValue("longest_consecutive_eligible_run", max((len(run) for run in runs), default=0), "count"),
                ),
            )
        )
        return tuple(findings)

    for run_index, run in enumerate(evaluable_runs):
        run_breaths = tuple(breaths[index] for index in run)
        windows = _wake_windows(run_breaths)
        candidate_groups = _irregular_window_groups(windows)
        if candidate_groups:
            for group_index, group in enumerate(candidate_groups):
                first_window = windows[group[0]]
                last_window = windows[group[-1]]
                candidate_breaths = run_breaths[first_window[0] : last_window[0] + WAKE_WINDOW_BREATHS]
                findings.append(
                    _finding(
                        rule=QualityRule.LIKELY_WAKE_BREATHING,
                        status=QualityStatus.FLAGGED,
                        impact=QualityImpact.CAUTION,
                        reason="irregular_breathing_candidate",
                        evaluated_record_id=breath_series.record_id,
                        records=records,
                        provenance=provenance,
                        parameters=parameters,
                        measurements=(
                            QualityValue("candidate_breath_count", len(candidate_breaths), "count"),
                            QualityValue("irregular_window_count", len(group), "count"),
                            QualityValue("maximum_amplitude_cv", max(windows[index][2] for index in group)),
                            QualityValue("maximum_duration_cv", max(windows[index][1] for index in group)),
                        ),
                        limitations=(_WAKE_LIMITATION,),
                        capabilities=("sleep_wake_context",),
                        qualifier=f"candidate:{run_index}:{group_index}",
                        interval=(candidate_breaths[0].start_time_ms, candidate_breaths[-1].end_time_ms),
                    )
                )
        else:
            findings.append(
                _finding(
                    rule=QualityRule.LIKELY_WAKE_BREATHING,
                    status=QualityStatus.PASS,
                    impact=QualityImpact.NONE,
                    reason="condition_not_observed",
                    evaluated_record_id=breath_series.record_id,
                    records=records,
                    provenance=provenance,
                    parameters=parameters,
                    measurements=(
                        QualityValue("eligible_breath_count", len(run_breaths), "count"),
                        QualityValue("maximum_amplitude_cv", max(window[2] for window in windows)),
                        QualityValue("maximum_duration_cv", max(window[1] for window in windows)),
                    ),
                    limitations=(_WAKE_LIMITATION, "A pass means only that the version-1 candidate was not observed in this eligible interval; it does not prove sleep."),
                    capabilities=("sleep_wake_context",),
                    qualifier=f"pass:{run_index}",
                    interval=(run_breaths[0].start_time_ms, run_breaths[-1].end_time_ms),
                )
            )
    return tuple(findings)


def evaluate_signal_quality(session: SessionRecord, breath_series: ValidatedBreathSeries | None = None) -> SignalQualityReport:
    """Evaluate the three S20 rules in their accepted dependency order."""

    if breath_series is not None and not isinstance(breath_series, ValidatedBreathSeries):
        raise QualityModelError("Signal quality requires a ValidatedBreathSeries or null.")
    findings = (
        *evaluate_large_leak(session),
        *evaluate_signal_artifacts(session, "flow_rate"),
        *evaluate_signal_artifacts(session, "mask_pressure"),
        *evaluate_likely_wake_breathing(session, breath_series),
    )
    identity = f"{session.record_id}|{breath_series.record_id if breath_series else None}|{','.join(sorted(finding.record_id for finding in findings))}"
    return SignalQualityReport(
        record_id=f"signal-quality-report:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        session_record_id=session.record_id,
        breath_series_record_id=None if breath_series is None else breath_series.record_id,
        findings=findings,
    )


def _machine_large_leak_findings(
    session: SessionRecord,
    start: int,
    end: int,
    parameters: tuple[QualityValue, ...],
) -> tuple[QualityFinding, ...]:
    findings = []
    for event in session.events:
        if event.event_kind != "large_leak" or event.duration_ms <= 0:
            continue
        interval = _clip((event.start_time_ms, event.start_time_ms + event.duration_ms), max(start, session.start_time_ms), min(end, session.end_time_ms))
        if interval is None:
            continue
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.FLAGGED,
                impact=QualityImpact.EXCLUDE_INTERVAL,
                reason="machine_large_leak_span",
                evaluated_record_id=event.record_id,
                records=(session.record_id, event.record_id),
                provenance=(session.provenance.record_id, event.provenance.record_id),
                parameters=parameters,
                measurements=(
                    QualityValue("clipped_duration_ms", interval[1] - interval[0], "ms"),
                    QualityValue("event_completeness", _provenance_text(session, "events.completeness")),
                    QualityValue("raw_duration_ms", event.duration_ms, "ms"),
                    QualityValue("raw_end_time_ms", event.start_time_ms + event.duration_ms, "ms"),
                    QualityValue("raw_start_time_ms", event.start_time_ms, "ms"),
                ),
                limitations=(_LEAK_LIMITATION,),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier=event.record_id,
                interval=interval,
            )
        )
    return tuple(findings)


def _threshold_leak_intervals(leak: SignalRecord, start: int, end: int) -> tuple[Interval, ...]:
    intervals = []
    for segment in leak.segments:
        for sample_time, following_time, value in zip(segment.sample_times_ms, segment.sample_times_ms[1:], segment.values):
            if value < LARGE_LEAK_THRESHOLD_L_MIN or following_time <= sample_time:
                continue
            interval = _clip((sample_time, following_time), start, end)
            if interval is not None:
                intervals.append(interval)
    return _merge(intervals)


def _final_leak_point_findings(
    session: SessionRecord,
    leak: SignalRecord,
    start: int,
    end: int,
    parameters: tuple[QualityValue, ...],
    records: tuple[str, ...],
    provenance: tuple[str, ...],
) -> tuple[QualityFinding, ...]:
    findings = []
    for segment in leak.segments:
        sample_time = segment.sample_times_ms[-1]
        value = segment.values[-1]
        if value < LARGE_LEAK_THRESHOLD_L_MIN or sample_time < start or sample_time >= end:
            continue
        findings.append(
            _finding(
                rule=QualityRule.LARGE_LEAK,
                status=QualityStatus.FLAGGED,
                impact=QualityImpact.CAUTION,
                reason="threshold_exceeded",
                evaluated_record_id=leak.record_id,
                records=records,
                provenance=provenance,
                parameters=parameters,
                measurements=(
                    QualityValue("observed_leak_l_min", value, "L/min"),
                    QualityValue("point_observation_time_ms", sample_time, "ms"),
                ),
                limitations=(_LEAK_LIMITATION, "A final sparse update is point evidence only and creates no excluded interval."),
                capabilities=("flow_morphology", "event_rate", "pressure_response", "leak_quality"),
                qualifier=f"final-point:{segment.record_id}:{sample_time}",
            )
        )
    return tuple(findings)


def _peak_sparse_value(leak: SignalRecord, start: TimestampMs, end: TimestampMs) -> float:
    values = [
        value
        for segment in leak.segments
        for sample_time, following_time, value in zip(segment.sample_times_ms, segment.sample_times_ms[1:], segment.values)
        if sample_time < end and following_time > start
    ]
    return max(values)


def _maximum_sparse_evidence(leak: SignalRecord, start: TimestampMs, end: TimestampMs) -> float:
    values = [
        value
        for segment in leak.segments
        for sample_time, following_time, value in zip(segment.sample_times_ms, segment.sample_times_ms[1:], segment.values)
        if sample_time < end and following_time > start
    ]
    values.extend(segment.values[-1] for segment in leak.segments if start <= segment.sample_times_ms[-1] < end)
    return max(values)


def _digital_clipping_findings(
    segment: SignalSegmentRecord,
    records: tuple[str, ...],
    provenance: tuple[str, ...],
    parameters: tuple[QualityValue, ...],
    signal_kind: str,
    unit: str,
    requested_start: int,
    requested_end: int,
) -> tuple[QualityFinding, ...]:
    gain = _provenance_number(segment, "segment.gain_per_raw_unit")
    offset = _provenance_number(segment, "segment.offset")
    segment_interval = _clip((segment.start_time_ms, segment.end_time_ms), requested_start, requested_end)
    assert segment_interval is not None
    detector_parameters = parameters + (
        QualityValue("artifact_detector", "digital_clipping"),
        QualityValue("raw_count_reconstruction_abs_tolerance", ARTIFACT_RAW_COUNT_ABS_TOLERANCE, "raw count"),
        QualityValue("source_gain_per_raw_unit", gain),
        QualityValue("source_offset", offset),
    )
    if gain is None or offset is None or gain == 0:
        return (_artifact_insufficient(segment, records, provenance, detector_parameters, signal_kind, "digital_clipping", segment_interval),)
    findings = []
    for index, (sample_time, value) in enumerate(zip(segment.sample_times_ms, segment.values)):
        raw_value = (value - offset) / gain
        endpoint = next(
            (
                candidate
                for candidate in (-32_768, 32_767)
                if math.isclose(raw_value, candidate, rel_tol=0.0, abs_tol=ARTIFACT_RAW_COUNT_ABS_TOLERANCE)
            ),
            None,
        )
        if endpoint is None:
            continue
        interval = _clip((sample_time, _sample_end(segment, index)), requested_start, requested_end)
        if interval is None:
            continue
        findings.append(
            _finding(
                rule=QualityRule.SIGNAL_ARTIFACT,
                status=QualityStatus.FLAGGED,
                impact=QualityImpact.EXCLUDE_INTERVAL,
                reason="digital_clipping",
                evaluated_record_id=segment.record_id,
                records=records,
                provenance=provenance,
                parameters=detector_parameters,
                measurements=(QualityValue("canonical_sample_value", value, unit), QualityValue("reconstructed_raw_value", endpoint, "raw count")),
                limitations=(_ARTIFACT_LIMITATION,),
                capabilities=("waveform_morphology",),
                qualifier=f"{signal_kind}:digital:{index}",
                interval=interval,
            )
        )
    if findings:
        return tuple(findings)
    return (
        _finding(
            rule=QualityRule.SIGNAL_ARTIFACT,
            status=QualityStatus.PASS,
            impact=QualityImpact.NONE,
            reason="condition_not_observed",
            evaluated_record_id=segment.record_id,
            records=records,
            provenance=provenance,
            parameters=detector_parameters,
            measurements=(QualityValue("evaluated_sample_count", len(segment.values), "count"),),
            limitations=(_ARTIFACT_LIMITATION,),
            capabilities=("waveform_morphology",),
            qualifier=f"{signal_kind}:digital-pass",
            interval=segment_interval,
        ),
    )


def _isolated_impulse_findings(
    segment: SignalSegmentRecord,
    records: tuple[str, ...],
    provenance: tuple[str, ...],
    parameters: tuple[QualityValue, ...],
    signal_kind: str,
    impulse_threshold: float,
    neighbor_tolerance: float,
    unit: str,
    requested_start: int,
    requested_end: int,
) -> tuple[QualityFinding, ...]:
    detector_parameters = parameters + (QualityValue("artifact_detector", "isolated_impulse"),)
    segment_interval = _clip((segment.start_time_ms, segment.end_time_ms), requested_start, requested_end)
    assert segment_interval is not None
    if len(segment.values) < 3:
        return (_artifact_insufficient(segment, records, provenance, detector_parameters, signal_kind, "isolated_impulse", segment_interval),)
    findings = []
    for index in range(1, len(segment.values) - 1):
        previous, center, following = segment.values[index - 1 : index + 2]
        if abs(center - previous) < impulse_threshold or abs(center - following) < impulse_threshold or abs(previous - following) > neighbor_tolerance:
            continue
        interval_end = segment.sample_times_ms[index + 2] if index + 2 < len(segment.sample_times_ms) else segment.end_time_ms
        interval = _clip((segment.sample_times_ms[index - 1], interval_end), requested_start, requested_end)
        if interval is None:
            continue
        findings.append(
            _finding(
                rule=QualityRule.SIGNAL_ARTIFACT,
                status=QualityStatus.FLAGGED,
                impact=QualityImpact.EXCLUDE_INTERVAL,
                reason="isolated_impulse",
                evaluated_record_id=segment.record_id,
                records=records,
                provenance=provenance,
                parameters=detector_parameters,
                measurements=(
                    QualityValue("center_to_following_jump", abs(center - following), unit),
                    QualityValue("center_to_previous_jump", abs(center - previous), unit),
                    QualityValue("neighbor_difference", abs(previous - following), unit),
                ),
                limitations=(_ARTIFACT_LIMITATION,),
                capabilities=("waveform_morphology",),
                qualifier=f"{signal_kind}:impulse:{index}",
                interval=interval,
            )
        )
    if findings:
        return tuple(findings)
    return (
        _finding(
            rule=QualityRule.SIGNAL_ARTIFACT,
            status=QualityStatus.PASS,
            impact=QualityImpact.NONE,
            reason="condition_not_observed",
            evaluated_record_id=segment.record_id,
            records=records,
            provenance=provenance,
            parameters=detector_parameters,
            measurements=(QualityValue("evaluated_interior_sample_count", len(segment.values) - 2, "count"),),
            limitations=(_ARTIFACT_LIMITATION,),
            capabilities=("waveform_morphology",),
            qualifier=f"{signal_kind}:impulse-pass",
            interval=segment_interval,
        ),
    )


def _artifact_insufficient(
    segment: SignalSegmentRecord,
    records: tuple[str, ...],
    provenance: tuple[str, ...],
    parameters: tuple[QualityValue, ...],
    signal_kind: str,
    detector: str,
    interval: Interval,
) -> QualityFinding:
    return _finding(
        rule=QualityRule.SIGNAL_ARTIFACT,
        status=QualityStatus.INSUFFICIENT_EVIDENCE,
        impact=QualityImpact.EXCLUDE_INTERVAL,
        reason="artifact_input_missing",
        evaluated_record_id=segment.record_id,
        records=records,
        provenance=provenance,
        parameters=parameters,
        measurements=(QualityValue("segment_sample_count", len(segment.values), "count"),),
        limitations=(_ARTIFACT_LIMITATION,),
        capabilities=("waveform_morphology",),
        qualifier=f"{signal_kind}:{detector}:insufficient",
        interval=interval,
    )


def _provenance_number(segment: SignalSegmentRecord, name: str) -> float | None:
    for value in segment.provenance.source_values:
        if value.name != name:
            continue
        try:
            parsed = json.loads(value.value)
        except json.JSONDecodeError:
            return None
        if type(parsed) not in (int, float):
            return None
        normalized = float(parsed)
        return normalized if math.isfinite(normalized) else None
    return None


def _provenance_text(session: SessionRecord, name: str) -> str | None:
    for value in session.provenance.source_values:
        if value.name != name:
            continue
        try:
            parsed = json.loads(value.value)
        except json.JSONDecodeError:
            parsed = value.value
        return parsed if type(parsed) is str else None
    return None


def _sample_end(segment: SignalSegmentRecord, index: int) -> TimestampMs:
    return segment.sample_times_ms[index + 1] if index + 1 < len(segment.sample_times_ms) else segment.end_time_ms


def _finding_interval(finding: QualityFinding) -> Interval | None:
    if finding.start_time_ms is None or finding.end_time_ms is None:
        return None
    return finding.start_time_ms, finding.end_time_ms


def _is_wake_prerequisite_failure(finding: QualityFinding, flow: SignalRecord) -> bool:
    if finding.status not in (QualityStatus.FLAGGED, QualityStatus.INSUFFICIENT_EVIDENCE):
        return False
    if finding.rule_id is QualityRule.MISSING_REQUIRED_SIGNAL:
        return True
    if finding.rule_id is QualityRule.LARGE_LEAK:
        return finding.status is QualityStatus.INSUFFICIENT_EVIDENCE or finding.start_time_ms is not None
    if finding.rule_id is QualityRule.SIGNAL_ARTIFACT:
        parameters = {value.name: value.value for value in finding.parameters}
        return parameters.get("signal_kind") == "flow_rate" or finding.evaluated_record_id in {flow.record_id, *(segment.record_id for segment in flow.segments)}
    return False


def _wake_insufficient(
    session: SessionRecord,
    *,
    records: Iterable[str],
    provenance: Iterable[str],
    parameters: tuple[QualityValue, ...],
    reason: str,
    qualifier: str,
    measurements: tuple[QualityValue, ...],
    interval: Interval | None = None,
) -> QualityFinding:
    return _finding(
        rule=QualityRule.LIKELY_WAKE_BREATHING,
        status=QualityStatus.INSUFFICIENT_EVIDENCE,
        impact=QualityImpact.EXCLUDE_INTERVAL if interval is not None else QualityImpact.BLOCK_REQUESTED_ANALYSIS,
        reason=reason,
        evaluated_record_id=session.record_id,
        records=records,
        provenance=provenance,
        parameters=parameters,
        measurements=measurements,
        limitations=(_WAKE_LIMITATION,),
        capabilities=("sleep_wake_context",),
        qualifier=qualifier,
        interval=interval,
    )


def _suppressed_breath_indexes(breaths: tuple[ValidatedBreath, ...], events: tuple[EventRecord, ...]) -> frozenset[int]:
    suppressed: set[int] = set()
    for event in events:
        if event.event_kind not in _RESPIRATORY_EVENT_KINDS:
            continue
        event_interval = (event.start_time_ms, event.start_time_ms + event.duration_ms)
        suppressed.update(index for index, breath in enumerate(breaths) if _overlaps((breath.start_time_ms, breath.end_time_ms), event_interval))
        following = [index for index, breath in enumerate(breaths) if breath.start_time_ms >= event_interval[1]]
        suppressed.update(following[:3])
    return frozenset(suppressed)


def _consecutive_breath_runs(breaths: tuple[ValidatedBreath, ...], eligible: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    runs: list[list[int]] = []
    for index in eligible:
        if not runs or index != runs[-1][-1] + 1 or breaths[runs[-1][-1]].end_time_ms != breaths[index].start_time_ms:
            runs.append([index])
        else:
            runs[-1].append(index)
    return tuple(tuple(run) for run in runs)


def _wake_windows(breaths: tuple[ValidatedBreath, ...]) -> tuple[tuple[int, float, float], ...]:
    windows = []
    for start in range(len(breaths) - WAKE_WINDOW_BREATHS + 1):
        window = breaths[start : start + WAKE_WINDOW_BREATHS]
        durations = tuple(breath.end_time_ms - breath.start_time_ms for breath in window)
        amplitudes = tuple(breath.peak_to_trough_l_min for breath in window)
        windows.append((start, _population_cv(durations), _population_cv(amplitudes)))
    return tuple(windows)


def _irregular_window_groups(windows: tuple[tuple[int, float, float], ...]) -> tuple[tuple[int, ...], ...]:
    groups: list[list[int]] = []
    for index, (_, duration_cv, amplitude_cv) in enumerate(windows):
        if duration_cv < WAKE_DURATION_CV_THRESHOLD or amplitude_cv < WAKE_AMPLITUDE_CV_THRESHOLD:
            continue
        if not groups or index != groups[-1][-1] + 1:
            groups.append([index])
        else:
            groups[-1].append(index)
    return tuple(tuple(group) for group in groups if len(group) >= WAKE_REQUIRED_IRREGULAR_WINDOWS)


def _population_cv(values: tuple[TimestampMs, ...] | tuple[float, ...]) -> float:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / mean


def _overlaps(left: Interval, right: Interval) -> bool:
    return left[0] < right[1] and left[1] > right[0]
