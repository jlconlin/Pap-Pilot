"""Deterministic version-1 structural quality rules for normalized PAP records."""

from collections.abc import Iterable, Mapping
import hashlib
import json
from typing import Final, TypeAlias

from pap_pilot.engine.model import NightRecord, SessionRecord, SignalRecord, SignalRepresentation
from pap_pilot.engine.quality.model import (
    SHORT_SESSION_THRESHOLD_MS,
    ClockCorrectionEvidence,
    ClockCorrectionEvidenceState,
    QualityFinding,
    QualityImpact,
    QualityModelError,
    QualityRule,
    QualityStatus,
    QualityValue,
    StructuralQualityReport,
    TimeBasis,
)


TimestampMs: TypeAlias = int | float
Interval: TypeAlias = tuple[TimestampMs, TimestampMs]

_SIGNAL_CONTRACTS: Final = {
    "flow_rate": (SignalRepresentation.UNIFORM_WAVEFORM, "L/min"),
    "mask_pressure": (SignalRepresentation.UNIFORM_WAVEFORM, "cm H₂O"),
    "leak_rate": (SignalRepresentation.TIMED_UPDATES, "L/min"),
}
_SUPPORTED_CORRECTION_TYPES: Final = frozenset({"dst", "offset", "reset", "timezone", "travel"})
_MISSING_LIMITATION: Final = "Coverage is derived from stored normalized segments and is not interpolated across gaps."
_ALIGNMENT_LIMITATION: Final = "Alignment compares stored Flow Rate and Mask Pressure segments and does not infer missing samples."
_SHORT_LIMITATION: Final = "The five-minute boundary is an engineering marker, not a sleep, adherence, or valid-night threshold."
_SPLIT_LIMITATION: Final = "A split night is retained and does not by itself make the night invalid."
_CLOCK_LIMITATION: Final = "Raw timestamps remain unchanged; corrected wall-clock values are separate evidence."


def evaluate_missing_required_signals(
    session: SessionRecord,
    required_signal_kinds: Iterable[str],
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> tuple[QualityFinding, ...]:
    """Evaluate version-1 coverage for each signal required by an analysis."""

    required = _signal_kinds(required_signal_kinds)
    start, end = _requested_interval(session, start_time_ms, end_time_ms)
    base_parameters = (
        QualityValue("requested_end_time_ms", end, "ms"),
        QualityValue("requested_start_time_ms", start, "ms"),
    )
    if not required:
        return (
            _finding(
                rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                status=QualityStatus.NOT_APPLICABLE,
                impact=QualityImpact.NONE,
                reason="rule_not_applicable",
                evaluated_record_id=session.record_id,
                records=(session.record_id,),
                provenance=(session.provenance.record_id,),
                parameters=base_parameters,
                measurements=(QualityValue("required_signal_count", 0, "count"),),
                limitations=(_MISSING_LIMITATION,),
                capabilities=("requested_analysis",),
                qualifier="none",
            ),
        )

    signals = {signal.signal_kind: signal for signal in session.signals}
    findings: list[QualityFinding] = []
    eligible_by_kind: dict[str, tuple[Interval, ...]] = {}
    for signal_kind in required:
        signal = signals.get(signal_kind)
        parameters = base_parameters + (QualityValue("required_signal_kind", signal_kind),)
        expected = _SIGNAL_CONTRACTS.get(signal_kind)
        if expected is None:
            findings.append(
                _finding(
                    rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                    status=QualityStatus.INSUFFICIENT_EVIDENCE,
                    impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                    reason="unsupported_signal_contract",
                    evaluated_record_id=session.record_id,
                    records=(session.record_id,),
                    provenance=(session.provenance.record_id,),
                    parameters=parameters,
                    measurements=(QualityValue("supported_signal_kinds", ",".join(sorted(_SIGNAL_CONTRACTS))),),
                    limitations=(_MISSING_LIMITATION,),
                    capabilities=("requested_analysis",),
                    qualifier=signal_kind,
                )
            )
            continue
        if signal is None:
            findings.append(
                _finding(
                    rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                    status=QualityStatus.INSUFFICIENT_EVIDENCE,
                    impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                    reason="channel_missing",
                    evaluated_record_id=session.record_id,
                    records=(session.record_id,),
                    provenance=(session.provenance.record_id,),
                    parameters=parameters,
                    measurements=(QualityValue("covered_duration_ms", 0, "ms"),),
                    limitations=(_MISSING_LIMITATION,),
                    capabilities=("requested_analysis",),
                    qualifier=signal_kind,
                )
            )
            continue

        records, provenance = _signal_sources(session, signal)
        if (signal.representation, signal.unit) != expected:
            findings.append(
                _finding(
                    rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                    status=QualityStatus.INSUFFICIENT_EVIDENCE,
                    impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                    reason="unsupported_signal_contract",
                    evaluated_record_id=signal.record_id,
                    records=records,
                    provenance=provenance,
                    parameters=parameters,
                    measurements=(
                        QualityValue("observed_representation", signal.representation.value),
                        QualityValue("observed_unit", signal.unit),
                    ),
                    limitations=(_MISSING_LIMITATION,),
                    capabilities=("requested_analysis",),
                    qualifier=signal_kind,
                )
            )
            continue

        coverage = _signal_coverage(signal, start, end)
        if not coverage:
            findings.append(
                _finding(
                    rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                    status=QualityStatus.INSUFFICIENT_EVIDENCE,
                    impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                    reason=_availability_reason(signal),
                    evaluated_record_id=signal.record_id,
                    records=records,
                    provenance=provenance,
                    parameters=parameters,
                    measurements=(QualityValue("covered_duration_ms", 0, "ms"),),
                    limitations=(_MISSING_LIMITATION,),
                    capabilities=("requested_analysis",),
                    qualifier=signal_kind,
                )
            )
            continue

        eligible_by_kind[signal_kind] = coverage
        gaps = _subtract((start, end), coverage)
        covered_duration = sum(interval_end - interval_start for interval_start, interval_end in coverage)
        if not gaps:
            findings.append(
                _finding(
                    rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                    status=QualityStatus.PASS,
                    impact=QualityImpact.NONE,
                    reason="condition_not_observed",
                    evaluated_record_id=signal.record_id,
                    records=records,
                    provenance=provenance,
                    parameters=parameters,
                    measurements=(QualityValue("covered_duration_ms", covered_duration, "ms"),),
                    limitations=(_MISSING_LIMITATION,),
                    capabilities=("requested_analysis",),
                    qualifier=signal_kind,
                )
            )
        else:
            for gap_start, gap_end in gaps:
                findings.append(
                    _finding(
                        rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                        status=QualityStatus.FLAGGED,
                        impact=QualityImpact.EXCLUDE_INTERVAL,
                        reason="coverage_gap",
                        evaluated_record_id=signal.record_id,
                        records=records,
                        provenance=provenance,
                        parameters=parameters,
                        measurements=(
                            QualityValue("covered_duration_ms", covered_duration, "ms"),
                            QualityValue("gap_duration_ms", gap_end - gap_start, "ms"),
                        ),
                        limitations=(_MISSING_LIMITATION,),
                        capabilities=("requested_analysis",),
                        qualifier=f"{signal_kind}:{gap_start}:{gap_end}",
                        interval=(gap_start, gap_end),
                    )
                )

    if len(eligible_by_kind) == len(required):
        common: tuple[Interval, ...] = ((start, end),)
        for signal_kind in required:
            common = _intersect_sets(common, eligible_by_kind[signal_kind])
        if not common:
            records = [session.record_id]
            provenance = [session.provenance.record_id]
            for signal_kind in required:
                signal = signals[signal_kind]
                signal_records, signal_provenance = _signal_sources(session, signal)
                records.extend(signal_records)
                provenance.extend(signal_provenance)
            findings.append(
                _finding(
                    rule=QualityRule.MISSING_REQUIRED_SIGNAL,
                    status=QualityStatus.INSUFFICIENT_EVIDENCE,
                    impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
                    reason="no_common_eligible_interval",
                    evaluated_record_id=session.record_id,
                    records=records,
                    provenance=provenance,
                    parameters=base_parameters + (QualityValue("required_signal_kinds", ",".join(required)),),
                    measurements=(QualityValue("common_covered_duration_ms", 0, "ms"),),
                    limitations=(_MISSING_LIMITATION,),
                    capabilities=("requested_analysis",),
                    qualifier="common",
                )
            )
    return tuple(findings)


def evaluate_flow_pressure_alignment(
    session: SessionRecord,
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> QualityFinding:
    """Compare exact Flow Rate and Mask Pressure segment geometry and timestamps."""

    start, end = _requested_interval(session, start_time_ms, end_time_ms)
    parameters = (
        QualityValue("requested_end_time_ms", end, "ms"),
        QualityValue("requested_start_time_ms", start, "ms"),
    )
    signals = {signal.signal_kind: signal for signal in session.signals}
    flow = signals.get("flow_rate")
    pressure = signals.get("mask_pressure")
    compatible = tuple(
        signal
        for signal, signal_kind in ((flow, "flow_rate"), (pressure, "mask_pressure"))
        if signal is not None
        and (signal.representation, signal.unit) == _SIGNAL_CONTRACTS[signal_kind]
        and bool(_signal_coverage(signal, start, end))
    )
    if len(compatible) != 2:
        present = tuple(signal for signal in (flow, pressure) if signal is not None)
        records = [session.record_id]
        provenance = [session.provenance.record_id]
        for signal in present:
            signal_records, signal_provenance = _signal_sources(session, signal)
            records.extend(signal_records)
            provenance.extend(signal_provenance)
        return _finding(
            rule=QualityRule.FLOW_PRESSURE_MISALIGNMENT,
            status=QualityStatus.INSUFFICIENT_EVIDENCE,
            impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
            reason="paired_signal_unavailable",
            evaluated_record_id=session.record_id,
            records=records,
            provenance=provenance,
            parameters=parameters,
            measurements=(QualityValue("available_paired_signal_count", len(compatible), "count"),),
            limitations=(_ALIGNMENT_LIMITATION,),
            capabilities=("paired_pressure_response",),
            qualifier="unavailable",
        )

    assert flow is not None and pressure is not None
    flow_segments = _overlapping_segments(flow, start, end)
    pressure_segments = _overlapping_segments(pressure, start, end)
    records = (session.record_id, *_signal_sources(session, flow)[0], *_signal_sources(session, pressure)[0])
    provenance = (session.provenance.record_id, *_signal_sources(session, flow)[1], *_signal_sources(session, pressure)[1])
    reason: str | None = None
    mismatch_interval: Interval | None = None
    if len(flow_segments) != len(pressure_segments) or tuple((segment.start_time_ms, segment.end_time_ms) for segment in flow_segments) != tuple(
        (segment.start_time_ms, segment.end_time_ms) for segment in pressure_segments
    ):
        reason = "bounds_mismatch"
        mismatch_interval = _extent(flow_segments, pressure_segments, start, end)
    elif tuple(len(segment.sample_times_ms) for segment in flow_segments) != tuple(
        len(segment.sample_times_ms) for segment in pressure_segments
    ):
        reason = "sample_count_mismatch"
        mismatch_interval = _first_segment_mismatch_interval(flow_segments, pressure_segments, start, end, compare="count")
    elif tuple(segment.sample_times_ms for segment in flow_segments) != tuple(
        segment.sample_times_ms for segment in pressure_segments
    ):
        reason = "sample_time_mismatch"
        mismatch_interval = _first_segment_mismatch_interval(flow_segments, pressure_segments, start, end, compare="time")

    measurements = (
        QualityValue("flow_sample_count", sum(len(segment.sample_times_ms) for segment in flow_segments), "count"),
        QualityValue("flow_segment_count", len(flow_segments), "count"),
        QualityValue("mask_pressure_sample_count", sum(len(segment.sample_times_ms) for segment in pressure_segments), "count"),
        QualityValue("mask_pressure_segment_count", len(pressure_segments), "count"),
    )
    if reason is None:
        return _finding(
            rule=QualityRule.FLOW_PRESSURE_MISALIGNMENT,
            status=QualityStatus.PASS,
            impact=QualityImpact.NONE,
            reason="condition_not_observed",
            evaluated_record_id=session.record_id,
            records=records,
            provenance=provenance,
            parameters=parameters,
            measurements=measurements,
            limitations=(_ALIGNMENT_LIMITATION,),
            capabilities=("paired_pressure_response",),
            qualifier="pass",
        )
    return _finding(
        rule=QualityRule.FLOW_PRESSURE_MISALIGNMENT,
        status=QualityStatus.FLAGGED,
        impact=QualityImpact.EXCLUDE_INTERVAL,
        reason=reason,
        evaluated_record_id=session.record_id,
        records=records,
        provenance=provenance,
        parameters=parameters,
        measurements=measurements,
        limitations=(_ALIGNMENT_LIMITATION,),
        capabilities=("paired_pressure_response",),
        qualifier=reason,
        interval=mismatch_interval,
    )


def evaluate_short_session(session: SessionRecord) -> QualityFinding:
    """Flag a raw session duration below the exact five-minute boundary."""

    duration = session.end_time_ms - session.start_time_ms
    flagged = duration < SHORT_SESSION_THRESHOLD_MS
    return _finding(
        rule=QualityRule.SHORT_SESSION,
        status=QualityStatus.FLAGGED if flagged else QualityStatus.PASS,
        impact=QualityImpact.CAUTION if flagged else QualityImpact.NONE,
        reason="duration_below_300000_ms" if flagged else "condition_not_observed",
        evaluated_record_id=session.record_id,
        records=(session.record_id,),
        provenance=(session.provenance.record_id,),
        parameters=(QualityValue("short_session_threshold_ms", SHORT_SESSION_THRESHOLD_MS, "ms"),),
        measurements=(QualityValue("session_duration_ms", duration, "ms"),),
        limitations=(_SHORT_LIMITATION,),
        capabilities=("session_context",),
        qualifier=str(duration),
    )


def evaluate_split_session_night(night: NightRecord) -> QualityFinding:
    """Flag a normalized night containing more than one raw session."""

    session_count = len(night.sessions)
    measurements = [QualityValue("session_count", session_count, "count")]
    for index, (current, following) in enumerate(zip(night.sessions, night.sessions[1:])):
        measurements.append(QualityValue(f"inter_session_gap_{index}_ms", following.start_time_ms - current.end_time_ms, "ms"))
    flagged = session_count > 1
    records = (night.record_id, *(session.record_id for session in night.sessions))
    provenance = (night.provenance.record_id, *(session.provenance.record_id for session in night.sessions))
    return _finding(
        rule=QualityRule.SPLIT_SESSION_NIGHT,
        status=QualityStatus.FLAGGED if flagged else QualityStatus.PASS,
        impact=QualityImpact.CAUTION if flagged else QualityImpact.NONE,
        reason="multiple_sessions" if flagged else "condition_not_observed",
        evaluated_record_id=night.record_id,
        records=records,
        provenance=provenance,
        parameters=(QualityValue("split_when_session_count_above", 1, "count"),),
        measurements=tuple(measurements),
        limitations=(_SPLIT_LIMITATION,),
        capabilities=("night_aggregation",),
        qualifier=str(session_count),
    )


def evaluate_clock_correction_integrity(
    session: SessionRecord,
    evidence: ClockCorrectionEvidence | None = None,
    *,
    time_basis: TimeBasis = TimeBasis.CORRECTED_WALL_CLOCK,
) -> QualityFinding:
    """Evaluate explicit correction evidence without mutating raw timestamps."""

    if not isinstance(time_basis, TimeBasis):
        raise QualityModelError("The requested time basis has an unsupported value.")
    evidence = evidence or ClockCorrectionEvidence(ClockCorrectionEvidenceState.NOT_QUERIED)
    records = (session.record_id, *evidence.source_record_ids)
    provenance = (session.provenance.record_id,)
    parameters = (
        QualityValue("requested_time_basis", time_basis.value),
        QualityValue("supported_correction_types", ",".join(sorted(_SUPPORTED_CORRECTION_TYPES))),
    )
    measurements = [
        QualityValue("raw_end_time_ms", session.end_time_ms, "ms"),
        QualityValue("raw_start_time_ms", session.start_time_ms, "ms"),
    ]
    capabilities = ("corrected_wall_clock",) if time_basis is TimeBasis.CORRECTED_WALL_CLOCK else ("raw_duration_and_alignment",)
    if time_basis is TimeBasis.RAW_RELATIVE:
        return _finding(
            rule=QualityRule.CLOCK_CORRECTION_INTEGRITY,
            status=QualityStatus.PASS,
            impact=QualityImpact.NONE,
            reason="condition_not_observed",
            evaluated_record_id=session.record_id,
            records=records,
            provenance=provenance,
            parameters=parameters,
            measurements=tuple(measurements),
            limitations=(_CLOCK_LIMITATION, "This pass supports only calculations using a common raw relative time basis."),
            capabilities=capabilities,
            qualifier=f"raw:{evidence.state.value}",
        )

    if evidence.state in (ClockCorrectionEvidenceState.NOT_QUERIED,):
        return _clock_insufficient(session, records, provenance, parameters, measurements, capabilities, "correction_input_missing", evidence.state)
    if evidence.state is ClockCorrectionEvidenceState.RANGE_AMBIGUOUS:
        return _clock_insufficient(session, records, provenance, parameters, measurements, capabilities, "correction_range_ambiguous", evidence.state)
    if evidence.state is ClockCorrectionEvidenceState.UNSUPPORTED_DRIFT:
        return _clock_insufficient(session, records, provenance, parameters, measurements, capabilities, "unsupported_drift", evidence.state)
    if evidence.state is ClockCorrectionEvidenceState.STACKED_UNREPRODUCIBLE:
        return _clock_insufficient(session, records, provenance, parameters, measurements, capabilities, "stacked_correction_unreproducible", evidence.state)
    if evidence.state is ClockCorrectionEvidenceState.CONFIRMED_NONE:
        return _finding(
            rule=QualityRule.CLOCK_CORRECTION_INTEGRITY,
            status=QualityStatus.PASS,
            impact=QualityImpact.NONE,
            reason="condition_not_observed",
            evaluated_record_id=session.record_id,
            records=records,
            provenance=provenance,
            parameters=parameters,
            measurements=tuple(measurements),
            limitations=(_CLOCK_LIMITATION,),
            capabilities=capabilities,
            qualifier="confirmed_none",
        )

    assert evidence.total_offset_ms is not None
    assert evidence.corrected_start_time_ms is not None
    assert evidence.corrected_end_time_ms is not None
    measurements.extend(
        (
            QualityValue("corrected_end_time_ms", evidence.corrected_end_time_ms, "ms"),
            QualityValue("corrected_start_time_ms", evidence.corrected_start_time_ms, "ms"),
            QualityValue("total_offset_ms", evidence.total_offset_ms, "ms"),
        )
    )
    valid = (
        bool(set(evidence.correction_types))
        and set(evidence.correction_types).issubset(_SUPPORTED_CORRECTION_TYPES)
        and evidence.corrected_start_time_ms == session.start_time_ms + evidence.total_offset_ms
        and evidence.corrected_end_time_ms == session.end_time_ms + evidence.total_offset_ms
        and evidence.corrected_start_time_ms < evidence.corrected_end_time_ms
        and evidence.corrected_end_time_ms - evidence.corrected_start_time_ms == session.end_time_ms - session.start_time_ms
    )
    if not valid:
        return _clock_insufficient(session, records, provenance, parameters, measurements, capabilities, "corrected_timeline_invalid", evidence.state)
    return _finding(
        rule=QualityRule.CLOCK_CORRECTION_INTEGRITY,
        status=QualityStatus.FLAGGED,
        impact=QualityImpact.CAUTION,
        reason="supported_correction_present",
        evaluated_record_id=session.record_id,
        records=records,
        provenance=provenance,
        parameters=parameters + (QualityValue("correction_types", ",".join(evidence.correction_types)),),
        measurements=tuple(measurements),
        limitations=(_CLOCK_LIMITATION,),
        capabilities=capabilities,
        qualifier=f"constant:{evidence.total_offset_ms}",
    )


def evaluate_structural_quality(
    night: NightRecord,
    *,
    required_signal_kinds: Iterable[str] = (),
    require_flow_pressure_alignment: bool = False,
    time_basis: TimeBasis = TimeBasis.RAW_RELATIVE,
    clock_corrections: Mapping[str, ClockCorrectionEvidence] | None = None,
) -> StructuralQualityReport:
    """Evaluate only the five structural rules assigned to S19."""

    if type(require_flow_pressure_alignment) is not bool:
        raise QualityModelError("The flow-pressure alignment request must be Boolean.")
    if not isinstance(time_basis, TimeBasis):
        raise QualityModelError("The requested time basis has an unsupported value.")
    required = _signal_kinds(required_signal_kinds)
    if clock_corrections is not None and not isinstance(clock_corrections, Mapping):
        raise QualityModelError("Clock corrections must map session identifiers to correction evidence.")
    corrections = dict(clock_corrections or {})
    if any(type(session_id) is not str or not session_id.strip() for session_id in corrections):
        raise QualityModelError("Clock correction session identifiers must be nonempty text.")
    if any(not isinstance(evidence, ClockCorrectionEvidence) for evidence in corrections.values()):
        raise QualityModelError("Clock correction values must be ClockCorrectionEvidence records.")
    session_ids = {session.record_id for session in night.sessions}
    unknown = sorted(set(corrections) - session_ids)
    if unknown:
        raise QualityModelError(f"Clock correction evidence references unknown sessions: {', '.join(unknown)}.")
    findings = [evaluate_split_session_night(night)]
    for session in night.sessions:
        findings.append(evaluate_short_session(session))
        findings.extend(evaluate_missing_required_signals(session, required))
        if require_flow_pressure_alignment:
            findings.append(evaluate_flow_pressure_alignment(session))
        else:
            findings.append(_alignment_not_applicable(session))
        findings.append(evaluate_clock_correction_integrity(session, corrections.get(session.record_id), time_basis=time_basis))
    request_key = f"{night.record_id}|{','.join(required)}|{int(require_flow_pressure_alignment)}|{time_basis.value}|{','.join(sorted(finding.record_id for finding in findings))}"
    return StructuralQualityReport(
        record_id=f"quality-report:{hashlib.sha256(request_key.encode()).hexdigest()[:20]}",
        night_record_id=night.record_id,
        required_signal_kinds=required,
        require_flow_pressure_alignment=require_flow_pressure_alignment,
        time_basis=time_basis,
        findings=tuple(findings),
    )


def _alignment_not_applicable(session: SessionRecord) -> QualityFinding:
    return _finding(
        rule=QualityRule.FLOW_PRESSURE_MISALIGNMENT,
        status=QualityStatus.NOT_APPLICABLE,
        impact=QualityImpact.NONE,
        reason="rule_not_applicable",
        evaluated_record_id=session.record_id,
        records=(session.record_id,),
        provenance=(session.provenance.record_id,),
        parameters=(QualityValue("alignment_requested", False),),
        measurements=(),
        limitations=(_ALIGNMENT_LIMITATION,),
        capabilities=("paired_pressure_response",),
        qualifier="not-requested",
    )


def _clock_insufficient(
    session: SessionRecord,
    records: Iterable[str],
    provenance: Iterable[str],
    parameters: tuple[QualityValue, ...],
    measurements: Iterable[QualityValue],
    capabilities: tuple[str, ...],
    reason: str,
    state: ClockCorrectionEvidenceState,
) -> QualityFinding:
    return _finding(
        rule=QualityRule.CLOCK_CORRECTION_INTEGRITY,
        status=QualityStatus.INSUFFICIENT_EVIDENCE,
        impact=QualityImpact.BLOCK_REQUESTED_ANALYSIS,
        reason=reason,
        evaluated_record_id=session.record_id,
        records=records,
        provenance=provenance,
        parameters=parameters,
        measurements=tuple(measurements) + (QualityValue("correction_evidence_state", state.value),),
        limitations=(_CLOCK_LIMITATION,),
        capabilities=capabilities,
        qualifier=state.value,
    )


def _finding(
    *,
    rule: QualityRule,
    status: QualityStatus,
    impact: QualityImpact,
    reason: str,
    evaluated_record_id: str,
    records: Iterable[str],
    provenance: Iterable[str],
    parameters: Iterable[QualityValue],
    measurements: Iterable[QualityValue],
    limitations: Iterable[str],
    capabilities: Iterable[str],
    qualifier: str,
    interval: Interval | None = None,
) -> QualityFinding:
    start, end = interval if interval is not None else (None, None)
    source_records = tuple(sorted(set(records)))
    source_provenance = tuple(sorted(set(provenance)))
    parameter_values = tuple(parameters)
    measured_values = tuple(measurements)
    limitation_values = tuple(limitations)
    capability_values = tuple(capabilities)
    identity = f"{rule.value}|{status.value}|{impact.value}|{evaluated_record_id}|{reason}|{qualifier}|{start}|{end}|{source_records}|{source_provenance}|{parameter_values}|{measured_values}"
    return QualityFinding(
        record_id=f"quality:{rule.value}:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        rule_id=rule,
        status=status,
        impact=impact,
        reason_code=reason,
        evaluated_record_id=evaluated_record_id,
        source_record_ids=source_records,
        source_provenance_ids=source_provenance,
        parameters=parameter_values,
        measurements=measured_values,
        limitations=limitation_values,
        affected_capabilities=capability_values,
        start_time_ms=start,
        end_time_ms=end,
    )


def _signal_kinds(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise QualityModelError("Required signal kinds must be an iterable of names, not text.")
    try:
        normalized = tuple(values)
    except TypeError as error:
        raise QualityModelError("Required signal kinds must be iterable.") from error
    if any(type(value) is not str or not value.strip() for value in normalized):
        raise QualityModelError("Required signal kinds must be nonempty text.")
    if len(set(normalized)) != len(normalized):
        raise QualityModelError("Required signal kinds must be unique.")
    return tuple(sorted(normalized))


def _requested_interval(session: SessionRecord, start: int | None, end: int | None) -> tuple[int, int]:
    requested_start = session.start_time_ms if start is None else start
    requested_end = session.end_time_ms if end is None else end
    if type(requested_start) is not int or type(requested_end) is not int:
        raise QualityModelError("Requested interval boundaries must be integer milliseconds.")
    if requested_start < session.start_time_ms or requested_end > session.end_time_ms or requested_start >= requested_end:
        raise QualityModelError("The requested interval must be positive and contained in the session.")
    return requested_start, requested_end


def _signal_sources(session: SessionRecord, signal: SignalRecord) -> tuple[tuple[str, ...], tuple[str, ...]]:
    records = (session.record_id, signal.record_id, *(segment.record_id for segment in signal.segments))
    provenance = (
        session.provenance.record_id,
        signal.provenance.record_id,
        *(segment.provenance.record_id for segment in signal.segments),
    )
    return tuple(sorted(set(records))), tuple(sorted(set(provenance)))


def _availability_reason(signal: SignalRecord) -> str:
    for value in signal.provenance.source_values:
        if value.name != "signal.availability":
            continue
        try:
            availability = json.loads(value.value)
        except json.JSONDecodeError:
            availability = value.value
        if availability == "channel_missing":
            return "channel_missing"
        if availability == "data_missing":
            return "data_missing"
    return "data_missing"


def _signal_coverage(signal: SignalRecord, start: int, end: int) -> tuple[Interval, ...]:
    intervals: list[Interval] = []
    for segment in signal.segments:
        if signal.representation is SignalRepresentation.UNIFORM_WAVEFORM:
            candidate = (segment.start_time_ms, segment.end_time_ms)
            clipped = _clip(candidate, start, end)
            if clipped is not None:
                intervals.append(clipped)
        else:
            for current, following in zip(segment.sample_times_ms, segment.sample_times_ms[1:]):
                if following <= current:
                    continue
                clipped = _clip((current, following), start, end)
                if clipped is not None:
                    intervals.append(clipped)
    return _merge(intervals)


def _overlapping_segments(signal: SignalRecord, start: int, end: int) -> tuple:
    return tuple(segment for segment in signal.segments if segment.start_time_ms < end and segment.end_time_ms > start)


def _clip(interval: Interval, start: TimestampMs, end: TimestampMs) -> Interval | None:
    clipped = (max(interval[0], start), min(interval[1], end))
    return clipped if clipped[0] < clipped[1] else None


def _merge(intervals: Iterable[Interval]) -> tuple[Interval, ...]:
    ordered = sorted(intervals)
    merged: list[Interval] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)


def _subtract(scope: Interval, coverage: tuple[Interval, ...]) -> tuple[Interval, ...]:
    gaps: list[Interval] = []
    cursor = scope[0]
    for start, end in coverage:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < scope[1]:
        gaps.append((cursor, scope[1]))
    return tuple(gaps)


def _intersect_sets(left: tuple[Interval, ...], right: tuple[Interval, ...]) -> tuple[Interval, ...]:
    intersections: list[Interval] = []
    for left_interval in left:
        for right_interval in right:
            clipped = _clip(left_interval, right_interval[0], right_interval[1])
            if clipped is not None:
                intersections.append(clipped)
    return _merge(intersections)


def _extent(flow_segments: tuple, pressure_segments: tuple, start: int, end: int) -> Interval:
    boundaries = [value for segment in (*flow_segments, *pressure_segments) for value in (segment.start_time_ms, segment.end_time_ms)]
    if not boundaries:
        return start, end
    return max(start, min(boundaries)), min(end, max(boundaries))


def _first_segment_mismatch_interval(flow_segments: tuple, pressure_segments: tuple, start: int, end: int, *, compare: str) -> Interval:
    for flow, pressure in zip(flow_segments, pressure_segments):
        matches = len(flow.sample_times_ms) == len(pressure.sample_times_ms) if compare == "count" else flow.sample_times_ms == pressure.sample_times_ms
        if not matches:
            return max(start, flow.start_time_ms), min(end, flow.end_time_ms)
    return start, end
