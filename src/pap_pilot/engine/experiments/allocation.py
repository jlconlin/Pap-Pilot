"""Deterministic allocation of normalized nights around a confirmed change."""

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from typing import Final

from pap_pilot.engine.experiments.model import ExperimentEvent, ExperimentEventType, SettingChangeConfirmedPayload
from pap_pilot.engine.model import NightRecord, SourceClass
from pap_pilot.engine.quality import QualityFinding, QualityImpact, SignalQualityReport, StructuralQualityReport


EXPERIMENT_ALLOCATION_RULE_SET_ID: Final = "pap-pilot.experiment-night-allocation"
EXPERIMENT_ALLOCATION_RULE_SET_VERSION: Final = 1
EXPERIMENT_ALLOCATION_ENGINE_VERSION: Final = "0.1.0"


class ExperimentAllocationError(ValueError):
    """Raised when experiment nights cannot be allocated unambiguously."""


class ExperimentPeriod(StrEnum):
    """A night wholly before or after the confirmed application boundary."""

    BASELINE = "baseline"
    INTERVENTION = "intervention"


class NightAllocationStatus(StrEnum):
    """Whether an assigned night retains any eligible evidence."""

    INCLUDED = "included"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class AllocationInterval:
    """One half-open requested, eligible, or excluded session interval."""

    session_record_id: str
    start_time_ms: int | float
    end_time_ms: int | float
    quality_finding_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.session_record_id, "allocation session identifier")
        start = _timestamp(self.start_time_ms, "allocation interval start")
        end = _timestamp(self.end_time_ms, "allocation interval end")
        if start >= end:
            raise ExperimentAllocationError("An allocation interval must be positive and half-open.")
        finding_ids = _text_tuple(self.quality_finding_ids, "allocation quality finding identifiers")
        reasons = _text_tuple(self.reason_codes, "allocation reason codes")
        if bool(finding_ids) != bool(reasons):
            raise ExperimentAllocationError("An excluded allocation interval must retain both findings and reasons.")
        object.__setattr__(self, "start_time_ms", start)
        object.__setattr__(self, "end_time_ms", end)
        object.__setattr__(self, "quality_finding_ids", tuple(sorted(set(finding_ids))))
        object.__setattr__(self, "reason_codes", tuple(sorted(set(reasons))))


@dataclass(frozen=True, slots=True)
class NightAllocation:
    """One normalized night's deterministic experiment-period membership."""

    record_id: str
    night_record_id: str
    local_date: str
    period: ExperimentPeriod | None
    status: NightAllocationStatus
    requested_intervals: tuple[AllocationInterval, ...]
    eligible_intervals: tuple[AllocationInterval, ...]
    excluded_intervals: tuple[AllocationInterval, ...]
    exclusion_reason_codes: tuple[str, ...]
    structural_quality_report_id: str
    signal_quality_report_ids: tuple[str, ...]
    quality_finding_ids: tuple[str, ...]
    caution_finding_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    rule_set_id: str = EXPERIMENT_ALLOCATION_RULE_SET_ID
    rule_set_version: int = EXPERIMENT_ALLOCATION_RULE_SET_VERSION
    engine_version: str = EXPERIMENT_ALLOCATION_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "night-allocation identifier")
        _text(self.night_record_id, "allocated night identifier")
        _text(self.local_date, "allocated local date")
        if self.period is not None and not isinstance(self.period, ExperimentPeriod):
            raise ExperimentAllocationError("A night allocation has an unsupported experiment period.")
        if not isinstance(self.status, NightAllocationStatus):
            raise ExperimentAllocationError("A night allocation has an unsupported status.")
        requested = _interval_tuple(self.requested_intervals, "requested allocation intervals", required=True)
        eligible = _interval_tuple(self.eligible_intervals, "eligible allocation intervals")
        excluded = _interval_tuple(self.excluded_intervals, "excluded allocation intervals")
        reasons = _text_tuple(self.exclusion_reason_codes, "night exclusion reason codes")
        _text(self.structural_quality_report_id, "structural quality report identifier")
        signal_ids = _text_tuple(self.signal_quality_report_ids, "signal quality report identifiers")
        finding_ids = _text_tuple(self.quality_finding_ids, "quality finding identifiers")
        caution_ids = _text_tuple(self.caution_finding_ids, "caution finding identifiers")
        if self.status is NightAllocationStatus.INCLUDED and (self.period is None or not eligible or reasons):
            raise ExperimentAllocationError("An included night requires a period and eligible evidence without a night-level exclusion reason.")
        if self.status is NightAllocationStatus.EXCLUDED and (eligible or not reasons):
            raise ExperimentAllocationError("An excluded night requires no eligible evidence and at least one exclusion reason.")
        if self.period is None and "change_boundary_overlap" not in reasons:
            raise ExperimentAllocationError("Only a night crossing the confirmed change boundary can lack a period.")
        if not set(caution_ids).issubset(finding_ids):
            raise ExperimentAllocationError("Caution findings must be part of the allocation's quality evidence.")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise ExperimentAllocationError("Night allocations must be companion-derived.")
        if (self.rule_set_id, self.rule_set_version, self.engine_version) != (EXPERIMENT_ALLOCATION_RULE_SET_ID, EXPERIMENT_ALLOCATION_RULE_SET_VERSION, EXPERIMENT_ALLOCATION_ENGINE_VERSION):
            raise ExperimentAllocationError("The night-allocation rule-set identity or version is unsupported.")
        object.__setattr__(self, "requested_intervals", requested)
        object.__setattr__(self, "eligible_intervals", eligible)
        object.__setattr__(self, "excluded_intervals", excluded)
        object.__setattr__(self, "exclusion_reason_codes", tuple(sorted(set(reasons))))
        object.__setattr__(self, "signal_quality_report_ids", tuple(sorted(set(signal_ids))))
        object.__setattr__(self, "quality_finding_ids", tuple(sorted(set(finding_ids))))
        object.__setattr__(self, "caution_finding_ids", tuple(sorted(set(caution_ids))))


@dataclass(frozen=True, slots=True)
class ExperimentNightAllocation:
    """Versioned allocation result for one confirmed setting change."""

    record_id: str
    setting_change_event_id: str
    applied_at_ms: int
    nights: tuple[NightAllocation, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    rule_set_id: str = EXPERIMENT_ALLOCATION_RULE_SET_ID
    rule_set_version: int = EXPERIMENT_ALLOCATION_RULE_SET_VERSION
    engine_version: str = EXPERIMENT_ALLOCATION_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "experiment night-allocation identifier")
        _text(self.setting_change_event_id, "setting-change event identifier")
        if type(self.applied_at_ms) is not int:
            raise ExperimentAllocationError("The confirmed application timestamp must be an integer.")
        if type(self.nights) is not tuple or not self.nights or any(not isinstance(value, NightAllocation) for value in self.nights):
            raise ExperimentAllocationError("An experiment allocation requires an immutable nonempty tuple of allocated nights.")
        if len({value.night_record_id for value in self.nights}) != len(self.nights) or len({value.local_date for value in self.nights}) != len(self.nights):
            raise ExperimentAllocationError("Allocated night identifiers and local dates must be unique.")
        if tuple(sorted(self.nights, key=lambda value: (value.local_date, value.night_record_id))) != self.nights:
            raise ExperimentAllocationError("Allocated nights must be ordered by local date and identifier.")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise ExperimentAllocationError("Experiment allocations must be companion-derived.")
        if (self.rule_set_id, self.rule_set_version, self.engine_version) != (EXPERIMENT_ALLOCATION_RULE_SET_ID, EXPERIMENT_ALLOCATION_RULE_SET_VERSION, EXPERIMENT_ALLOCATION_ENGINE_VERSION):
            raise ExperimentAllocationError("The experiment-allocation rule-set identity or version is unsupported.")

    def included(self, period: ExperimentPeriod) -> tuple[NightAllocation, ...]:
        """Return included nights in one period and stable local-date order."""

        if not isinstance(period, ExperimentPeriod):
            raise ExperimentAllocationError("An allocation query requires a supported experiment period.")
        return tuple(value for value in self.nights if value.period is period and value.status is NightAllocationStatus.INCLUDED)

    @property
    def excluded(self) -> tuple[NightAllocation, ...]:
        """Return all nights excluded by boundary or quality evidence."""

        return tuple(value for value in self.nights if value.status is NightAllocationStatus.EXCLUDED)


def allocate_experiment_nights(
    nights: tuple[NightRecord, ...],
    setting_change_event: ExperimentEvent,
    structural_quality_reports: tuple[StructuralQualityReport, ...],
    signal_quality_reports: tuple[SignalQualityReport, ...] = (),
) -> ExperimentNightAllocation:
    """Assign whole nights around an explicit boundary and apply existing quality impacts."""

    normalized_nights = _nights(nights)
    change = _confirmed_change(setting_change_event)
    structural_by_night = _structural_reports(normalized_nights, structural_quality_reports)
    signal_by_night = _signal_reports(normalized_nights, signal_quality_reports)
    allocations = tuple(
        _allocate_night(night, setting_change_event, change, structural_by_night[night.record_id], signal_by_night[night.record_id])
        for night in normalized_nights
    )
    identity = "|".join((setting_change_event.record_id, str(change.applied_at_ms), *(value.record_id for value in allocations)))
    return ExperimentNightAllocation(
        record_id=f"experiment-night-allocation:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        setting_change_event_id=setting_change_event.record_id,
        applied_at_ms=change.applied_at_ms,
        nights=allocations,
    )


def _allocate_night(
    night: NightRecord,
    event: ExperimentEvent,
    change: SettingChangeConfirmedPayload,
    structural: StructuralQualityReport,
    signal_reports: tuple[SignalQualityReport, ...],
) -> NightAllocation:
    requested = tuple(AllocationInterval(session.record_id, session.start_time_ms, session.end_time_ms) for session in night.sessions)
    night_start = min(value.start_time_ms for value in night.sessions)
    night_end = max(value.end_time_ms for value in night.sessions)
    findings = (*structural.findings, *(finding for report in signal_reports for finding in report.findings))
    finding_ids = tuple(finding.record_id for finding in findings)
    caution_ids = tuple(finding.record_id for finding in findings if finding.impact is QualityImpact.CAUTION)
    report_ids = tuple(report.record_id for report in signal_reports)
    if night_start < change.applied_at_ms < night_end:
        return _night_result(night, event, None, NightAllocationStatus.EXCLUDED, requested, (), requested, ("change_boundary_overlap",), structural.record_id, report_ids, finding_ids, caution_ids)
    period = ExperimentPeriod.BASELINE if night_end <= change.applied_at_ms else ExperimentPeriod.INTERVENTION
    blockers = tuple(finding for finding in findings if finding.impact is QualityImpact.BLOCK_REQUESTED_ANALYSIS)
    if blockers:
        reasons = tuple(finding.reason_code for finding in blockers)
        excluded = tuple(AllocationInterval(value.session_record_id, value.start_time_ms, value.end_time_ms, tuple(finding.record_id for finding in blockers), reasons) for value in requested)
        return _night_result(night, event, period, NightAllocationStatus.EXCLUDED, requested, (), excluded, ("quality_block_requested_analysis", *reasons), structural.record_id, report_ids, finding_ids, caution_ids)
    excluded = _quality_excluded_intervals(night, findings)
    eligible = tuple(interval for session in night.sessions for interval in _subtract_session(session.record_id, session.start_time_ms, session.end_time_ms, excluded))
    if not eligible:
        reasons = tuple(sorted({reason for value in excluded for reason in value.reason_codes}))
        return _night_result(night, event, period, NightAllocationStatus.EXCLUDED, requested, (), excluded, ("no_eligible_interval", *reasons), structural.record_id, report_ids, finding_ids, caution_ids)
    return _night_result(night, event, period, NightAllocationStatus.INCLUDED, requested, eligible, excluded, (), structural.record_id, report_ids, finding_ids, caution_ids)


def _night_result(night: NightRecord, event: ExperimentEvent, period: ExperimentPeriod | None, status: NightAllocationStatus, requested: tuple[AllocationInterval, ...], eligible: tuple[AllocationInterval, ...], excluded: tuple[AllocationInterval, ...], reasons: tuple[str, ...], structural_id: str, signal_ids: tuple[str, ...], finding_ids: tuple[str, ...], caution_ids: tuple[str, ...]) -> NightAllocation:
    identity = "|".join((night.record_id, event.record_id, "boundary" if period is None else period.value, status.value, structural_id, *sorted(signal_ids), *sorted(finding_ids), *(f"{value.session_record_id}:{value.start_time_ms}:{value.end_time_ms}:{','.join(value.quality_finding_ids)}" for value in excluded)))
    return NightAllocation(
        record_id=f"night-allocation:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        night_record_id=night.record_id,
        local_date=night.local_date,
        period=period,
        status=status,
        requested_intervals=requested,
        eligible_intervals=eligible,
        excluded_intervals=excluded,
        exclusion_reason_codes=reasons,
        structural_quality_report_id=structural_id,
        signal_quality_report_ids=signal_ids,
        quality_finding_ids=finding_ids,
        caution_finding_ids=caution_ids,
    )


def _quality_excluded_intervals(night: NightRecord, findings: tuple[QualityFinding, ...]) -> tuple[AllocationInterval, ...]:
    intervals = []
    for session in night.sessions:
        for finding in findings:
            if finding.impact not in {QualityImpact.EXCLUDE_INTERVAL, QualityImpact.EXCLUDE_SESSION}:
                continue
            applies = finding.evaluated_record_id in {night.record_id, session.record_id} or night.record_id in finding.source_record_ids or session.record_id in finding.source_record_ids
            if not applies:
                continue
            if finding.impact is QualityImpact.EXCLUDE_SESSION:
                start, end = session.start_time_ms, session.end_time_ms
            elif finding.start_time_ms is not None and finding.end_time_ms is not None:
                start, end = max(session.start_time_ms, finding.start_time_ms), min(session.end_time_ms, finding.end_time_ms)
            else:
                continue
            if start < end:
                intervals.append(AllocationInterval(session.record_id, start, end, (finding.record_id,), (finding.reason_code,)))
    return _union_intervals(intervals)


def _union_intervals(intervals: list[AllocationInterval]) -> tuple[AllocationInterval, ...]:
    result = []
    for interval in sorted(intervals, key=lambda value: (value.session_record_id, value.start_time_ms, value.end_time_ms)):
        if not result or result[-1].session_record_id != interval.session_record_id or result[-1].end_time_ms < interval.start_time_ms:
            result.append(interval)
            continue
        previous = result.pop()
        result.append(AllocationInterval(previous.session_record_id, previous.start_time_ms, max(previous.end_time_ms, interval.end_time_ms), (*previous.quality_finding_ids, *interval.quality_finding_ids), (*previous.reason_codes, *interval.reason_codes)))
    return tuple(result)


def _subtract_session(session_id: str, start: int, end: int, exclusions: tuple[AllocationInterval, ...]) -> tuple[AllocationInterval, ...]:
    cursor = start
    result = []
    for value in exclusions:
        if value.session_record_id != session_id:
            continue
        if cursor < value.start_time_ms:
            result.append(AllocationInterval(session_id, cursor, value.start_time_ms))
        cursor = max(cursor, value.end_time_ms)
    if cursor < end:
        result.append(AllocationInterval(session_id, cursor, end))
    return tuple(result)


def _nights(values: object) -> tuple[NightRecord, ...]:
    if type(values) is not tuple or not values or any(not isinstance(value, NightRecord) for value in values):
        raise ExperimentAllocationError("Night allocation requires an immutable nonempty tuple of NightRecord values.")
    if len({value.record_id for value in values}) != len(values) or len({value.local_date for value in values}) != len(values):
        raise ExperimentAllocationError("Night identifiers and local dates must be unique.")
    ordered = tuple(sorted(values, key=lambda value: (value.local_date, value.record_id)))
    sessions = [session for night in ordered for session in night.sessions]
    if len({value.record_id for value in sessions}) != len(sessions):
        raise ExperimentAllocationError("Session identifiers must be unique across allocated nights.")
    chronological = sorted(sessions, key=lambda value: (value.start_time_ms, value.record_id))
    if any(current.end_time_ms > following.start_time_ms for current, following in zip(chronological, chronological[1:])):
        raise ExperimentAllocationError("Sessions in the allocation cannot overlap.")
    if any(max(session.end_time_ms for session in current.sessions) > min(session.start_time_ms for session in following.sessions) for current, following in zip(ordered, ordered[1:])):
        raise ExperimentAllocationError("Night local-date order must agree with session chronology.")
    return ordered


def _confirmed_change(event: object) -> SettingChangeConfirmedPayload:
    if not isinstance(event, ExperimentEvent) or event.event_type is not ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED or not isinstance(event.payload, SettingChangeConfirmedPayload):
        raise ExperimentAllocationError("Night allocation requires an explicit setting-change-confirmed event.")
    return event.payload


def _structural_reports(nights: tuple[NightRecord, ...], reports: object) -> dict[str, StructuralQualityReport]:
    if type(reports) is not tuple or any(not isinstance(value, StructuralQualityReport) for value in reports):
        raise ExperimentAllocationError("Structural quality evidence must be an immutable report tuple.")
    by_night = {value.night_record_id: value for value in reports}
    expected = {value.record_id for value in nights}
    if len(by_night) != len(reports) or set(by_night) != expected:
        raise ExperimentAllocationError("Exactly one structural quality report is required for every allocated night.")
    contracts = {(value.required_signal_kinds, value.require_flow_pressure_alignment, value.time_basis) for value in reports}
    if len(contracts) != 1:
        raise ExperimentAllocationError("Every night must use the same structural quality request.")
    return by_night


def _signal_reports(nights: tuple[NightRecord, ...], reports: object) -> dict[str, tuple[SignalQualityReport, ...]]:
    if type(reports) is not tuple or any(not isinstance(value, SignalQualityReport) for value in reports):
        raise ExperimentAllocationError("Signal quality evidence must be an immutable report tuple.")
    session_to_night = {session.record_id: night.record_id for night in nights for session in night.sessions}
    report_sessions = {value.session_record_id for value in reports}
    if len(report_sessions) != len(reports) or any(value.session_record_id not in session_to_night for value in reports):
        raise ExperimentAllocationError("Signal quality reports must uniquely reference sessions in the allocated nights.")
    if reports and report_sessions != set(session_to_night):
        raise ExperimentAllocationError("Signal quality evidence must cover every allocated session or be omitted for all sessions.")
    by_night = {night.record_id: [] for night in nights}
    for report in reports:
        by_night[session_to_night[report.session_record_id]].append(report)
    return {key: tuple(sorted(values, key=lambda value: value.session_record_id)) for key, values in by_night.items()}


def _interval_tuple(values: object, label: str, *, required: bool = False) -> tuple[AllocationInterval, ...]:
    if type(values) is not tuple or any(not isinstance(value, AllocationInterval) for value in values) or (required and not values):
        raise ExperimentAllocationError(f"The {label} must be an immutable{' nonempty' if required else ''} interval tuple.")
    return values


def _text_tuple(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
        raise ExperimentAllocationError(f"The {label} must be an immutable text tuple.")
    return values


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ExperimentAllocationError(f"The {label} must be nonempty text.")


def _timestamp(value: object, label: str) -> int | float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ExperimentAllocationError(f"The {label} must be numeric milliseconds.")
    return value
