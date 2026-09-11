"""Compose bounded, source-linked evidence for one generic PAP night view."""

from dataclasses import dataclass
from typing import Final, Iterable

from pap_pilot.engine.analysis import AnalysisAvailability, AnalysisNight
from pap_pilot.engine.model import EventRecord, NightRecord, ProvenanceRecord, SettingRecord, SignalRecord
from pap_pilot.engine.quality import QualityFinding, QualityStatus, SignalQualityReport, StructuralQualityReport


ANALYSIS_NIGHT_DETAIL_SCHEMA_ID: Final = "pap-pilot.analysis-night-detail"
ANALYSIS_NIGHT_DETAIL_SCHEMA_VERSION: Final = 1
ANALYSIS_NIGHT_DETAIL_RECORD_VERSION: Final = 1
ANALYSIS_NIGHT_SIGNAL_PREVIEW_MAX_SAMPLES: Final = 2_000
ANALYSIS_NIGHT_SIGNAL_PREVIEW_SELECTION: Final = "first_source_segment_first_samples"
ANALYSIS_NIGHT_DETAIL_LIMITATIONS: Final = (
    "Waveform previews display at most 2,000 exact samples from the first stored source segment; they are not selected for clinical importance.",
    "No preview is smoothed, interpolated, resampled, or joined across a source gap.",
    "Machine-labeled events and deterministic quality findings are evidence, not diagnoses.",
    "This view is read-only and cannot change PAP-device settings.",
)


class AnalysisNightDetailCompositionError(ValueError):
    """Raised when a night detail cannot be linked without guessing."""


@dataclass(frozen=True, slots=True)
class AnalysisNightSessionDetail:
    """One retained therapy session and its exact normalized boundaries."""

    session_record_id: str
    device_id: str
    start_time_ms: int
    end_time_ms: int
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisNightSettingDetail:
    """One observed normalized setting; never a requested device action."""

    setting_record_id: str
    session_record_id: str
    name: str
    value: bool | int | float | str
    unit: str | None
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisNightEventDetail:
    """One normalized machine-labeled event occurrence."""

    event_record_id: str
    session_record_id: str
    event_kind: str
    start_time_ms: int
    duration_ms: int
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisNightSignalDetail:
    """One signal with a bounded preview from its first stored segment."""

    signal_record_id: str
    session_record_id: str
    signal_kind: str
    unit: str
    representation: str
    value_semantics: str | None
    availability: AnalysisAvailability
    selected_segment_record_id: str | None
    selected_segment_start_time_ms: int | None
    selected_segment_end_time_ms: int | None
    selected_segment_interval_closure: str | None
    sample_interval_ms: float | None
    sample_times_ms: tuple[float, ...]
    values: tuple[float, ...]
    source_segment_count: int
    source_sample_count: int
    displayed_sample_count: int
    omitted_segment_count: int
    omitted_sample_count: int
    preview_selection: str | None
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisNightQualityFindingDetail:
    """One existing deterministic quality finding with its rule evidence."""

    finding_record_id: str
    quality_report_id: str
    report_kind: str
    session_record_id: str | None
    rule_id: str
    status: str
    impact: str
    reason_code: str
    evaluated_record_id: str
    start_time_ms: int | float | None
    end_time_ms: int | float | None
    parameters: tuple[tuple[str, bool | int | float | str | None, str | None], ...]
    measurements: tuple[tuple[str, bool | int | float | str | None, str | None], ...]
    affected_capabilities: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisNightProvenanceDetail:
    """One normalized provenance record and its upstream references."""

    provenance_record_id: str
    source_classes: tuple[str, ...]
    source_system: str
    source_system_version: str | None
    source_schema_version: str | None
    producer: str
    producer_version: str
    parent_provenance_ids: tuple[str, ...]
    source_references: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AnalysisNightDetail:
    """Versioned read-only evidence projection used by the night browser view."""

    record_id: str
    night_record_id: str
    local_date: str
    timezone: str | None
    day_boundary_local_time: str | None
    availability: AnalysisAvailability
    sessions: tuple[AnalysisNightSessionDetail, ...]
    sessions_availability: AnalysisAvailability
    sessions_reason_codes: tuple[str, ...]
    settings: tuple[AnalysisNightSettingDetail, ...]
    settings_availability: AnalysisAvailability
    settings_reason_codes: tuple[str, ...]
    events: tuple[AnalysisNightEventDetail, ...]
    events_availability: AnalysisAvailability
    events_reason_codes: tuple[str, ...]
    signals: tuple[AnalysisNightSignalDetail, ...]
    signals_availability: AnalysisAvailability
    signals_reason_codes: tuple[str, ...]
    quality_findings: tuple[AnalysisNightQualityFindingDetail, ...]
    quality_availability: AnalysisAvailability
    quality_reason_codes: tuple[str, ...]
    quality_report_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    provenance: tuple[AnalysisNightProvenanceDetail, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...] = ANALYSIS_NIGHT_DETAIL_LIMITATIONS
    schema_id: str = ANALYSIS_NIGHT_DETAIL_SCHEMA_ID
    schema_version: int = ANALYSIS_NIGHT_DETAIL_SCHEMA_VERSION
    record_version: int = ANALYSIS_NIGHT_DETAIL_RECORD_VERSION


def compose_analysis_night_details(
    nights: tuple[NightRecord, ...],
    *,
    structural_quality_reports: tuple[StructuralQualityReport, ...] = (),
    signal_quality_reports: tuple[SignalQualityReport, ...] = (),
) -> tuple[AnalysisNightDetail, ...]:
    """Build deterministic detail views from already-normalized, evaluated records."""

    selected_nights = _typed_tuple(nights, NightRecord, "normalized nights")
    structural = _typed_tuple(structural_quality_reports, StructuralQualityReport, "structural quality reports")
    signal_quality = _typed_tuple(signal_quality_reports, SignalQualityReport, "signal quality reports")
    _unique(tuple(value.record_id for value in selected_nights), "normalized night identifiers")
    _unique(tuple(value.record_id for value in structural), "structural quality report identifiers")
    _unique(tuple(value.record_id for value in signal_quality), "signal quality report identifiers")
    _unique(tuple(value.record_id for value in (*structural, *signal_quality)), "quality report identifiers")

    night_by_session = {
        session.record_id: night.record_id
        for night in selected_nights
        for session in night.sessions
    }
    if len(night_by_session) != sum(len(value.sessions) for value in selected_nights):
        raise AnalysisNightDetailCompositionError("Session identifiers must be unique across night details.")
    night_ids = {value.record_id for value in selected_nights}
    if any(value.night_record_id not in night_ids for value in structural):
        raise AnalysisNightDetailCompositionError("Every structural quality report must resolve to a detail night.")
    if any(value.session_record_id not in night_by_session for value in signal_quality):
        raise AnalysisNightDetailCompositionError("Every signal quality report must resolve to a detail session.")

    return tuple(
        _compose_night_detail(
            night,
            tuple(sorted((value for value in structural if value.night_record_id == night.record_id), key=lambda value: value.record_id)),
            tuple(sorted((value for value in signal_quality if night_by_session[value.session_record_id] == night.record_id), key=lambda value: value.record_id)),
        )
        for night in sorted(selected_nights, key=lambda value: (value.local_date, value.record_id))
    )


def unavailable_analysis_night_detail(night: AnalysisNight) -> AnalysisNightDetail:
    """Preserve a known night while stating that its detailed source was not supplied."""

    if not isinstance(night, AnalysisNight):
        raise AnalysisNightDetailCompositionError("An unavailable detail requires an analysis night.")
    reason = ("night_detail_source_not_configured",)
    return AnalysisNightDetail(
        record_id=f"analysis-night-detail:{night.night_record_id}",
        night_record_id=night.night_record_id,
        local_date=night.local_date,
        timezone=None,
        day_boundary_local_time=None,
        availability=AnalysisAvailability.UNAVAILABLE,
        sessions=(),
        sessions_availability=AnalysisAvailability.UNAVAILABLE,
        sessions_reason_codes=reason,
        settings=(),
        settings_availability=AnalysisAvailability.UNAVAILABLE,
        settings_reason_codes=reason,
        events=(),
        events_availability=AnalysisAvailability.UNAVAILABLE,
        events_reason_codes=reason,
        signals=(),
        signals_availability=AnalysisAvailability.UNAVAILABLE,
        signals_reason_codes=reason,
        quality_findings=(),
        quality_availability=AnalysisAvailability.UNAVAILABLE,
        quality_reason_codes=reason,
        quality_report_ids=night.quality_report_ids,
        source_record_ids=night.source_record_ids,
        source_provenance_ids=night.source_provenance_ids,
        provenance=(),
        reason_codes=reason,
    )


def _compose_night_detail(
    night: NightRecord,
    structural_reports: tuple[StructuralQualityReport, ...],
    signal_reports: tuple[SignalQualityReport, ...],
) -> AnalysisNightDetail:
    sessions = tuple(
        AnalysisNightSessionDetail(
            session.record_id,
            session.device_id,
            session.start_time_ms,
            session.end_time_ms,
            (session.record_id,),
            _provenance_ids(session.provenance),
        )
        for session in night.sessions
    )
    settings = tuple(
        _setting_detail(session.record_id, setting)
        for session in night.sessions
        for setting in session.settings
    )
    events = tuple(
        _event_detail(session.record_id, event)
        for session in night.sessions
        for event in session.events
    )
    signals = tuple(
        _signal_detail(session.record_id, signal)
        for session in night.sessions
        for signal in session.signals
    )
    quality = tuple(
        _quality_detail(report.record_id, "structural", None, finding)
        for report in structural_reports
        for finding in report.findings
    ) + tuple(
        _quality_detail(report.record_id, "signal", report.session_record_id, finding)
        for report in signal_reports
        for finding in report.findings
    )

    normalized_records = (
        night,
        *(session for session in night.sessions),
        *(setting for session in night.sessions for setting in session.settings),
        *(event for session in night.sessions for event in session.events),
        *(signal for session in night.sessions for signal in session.signals),
        *(segment for session in night.sessions for signal in session.signals for segment in signal.segments),
    )
    provenance_by_id = {
        record.provenance.record_id: record.provenance
        for record in normalized_records
    }
    provenance = tuple(_provenance_detail(value) for value in sorted(provenance_by_id.values(), key=lambda value: value.record_id))
    quality_report_ids = tuple(value.record_id for value in (*structural_reports, *signal_reports))
    source_record_ids = _sorted_texts(
        *(record.record_id for record in normalized_records),
        quality_report_ids,
        *(value.finding_record_id for value in quality),
        *(identifier for value in quality for identifier in value.source_record_ids),
    )
    source_provenance_ids = _sorted_texts(
        *(value.provenance_record_id for value in provenance),
        *(identifier for value in quality for identifier in value.source_provenance_ids),
    )

    settings_availability = AnalysisAvailability.AVAILABLE if settings else AnalysisAvailability.UNAVAILABLE
    events_availability = AnalysisAvailability.AVAILABLE if events else AnalysisAvailability.UNAVAILABLE
    signal_states = tuple(value.availability for value in signals)
    signals_availability = _collection_availability(signal_states)
    quality_availability, quality_reasons = _quality_availability(quality, quality_report_ids)
    section_states = (settings_availability, events_availability, signals_availability, quality_availability)
    availability = AnalysisAvailability.AVAILABLE if all(value is AnalysisAvailability.AVAILABLE for value in section_states) else AnalysisAvailability.PARTIAL
    reasons = tuple(
        reason
        for condition, reason in (
            (settings_availability is not AnalysisAvailability.AVAILABLE, "settings_unavailable"),
            (events_availability is not AnalysisAvailability.AVAILABLE, "no_normalized_event_records"),
            (signals_availability is not AnalysisAvailability.AVAILABLE, "one_or_more_signal_previews_unavailable"),
            (quality_availability is not AnalysisAvailability.AVAILABLE, "quality_evidence_incomplete"),
        )
        if condition
    )
    return AnalysisNightDetail(
        record_id=f"analysis-night-detail:{night.record_id}",
        night_record_id=night.record_id,
        local_date=night.local_date,
        timezone=night.timezone,
        day_boundary_local_time=night.day_boundary_local_time,
        availability=availability,
        sessions=sessions,
        sessions_availability=AnalysisAvailability.AVAILABLE,
        sessions_reason_codes=(),
        settings=settings,
        settings_availability=settings_availability,
        settings_reason_codes=() if settings else ("settings_unavailable",),
        events=events,
        events_availability=events_availability,
        events_reason_codes=() if events else ("no_normalized_event_records",),
        signals=signals,
        signals_availability=signals_availability,
        signals_reason_codes=tuple(sorted({reason for value in signals for reason in value.reason_codes})) if signals else ("signals_unavailable",),
        quality_findings=quality,
        quality_availability=quality_availability,
        quality_reason_codes=quality_reasons,
        quality_report_ids=quality_report_ids,
        source_record_ids=source_record_ids,
        source_provenance_ids=source_provenance_ids,
        provenance=provenance,
        reason_codes=reasons,
    )


def _setting_detail(session_record_id: str, setting: SettingRecord) -> AnalysisNightSettingDetail:
    return AnalysisNightSettingDetail(
        setting.record_id,
        session_record_id,
        setting.name,
        setting.value,
        setting.unit,
        (setting.record_id,),
        _provenance_ids(setting.provenance),
    )


def _event_detail(session_record_id: str, event: EventRecord) -> AnalysisNightEventDetail:
    return AnalysisNightEventDetail(
        event.record_id,
        session_record_id,
        event.event_kind,
        event.start_time_ms,
        event.duration_ms,
        (event.record_id,),
        _provenance_ids(event.provenance),
    )


def _signal_detail(session_record_id: str, signal: SignalRecord) -> AnalysisNightSignalDetail:
    segment_count = len(signal.segments)
    source_sample_count = sum(len(value.values) for value in signal.segments)
    source_ids = (signal.record_id, *(value.record_id for value in signal.segments))
    provenance_ids = _sorted_texts(
        _provenance_ids(signal.provenance),
        *(identifier for segment in signal.segments for identifier in _provenance_ids(segment.provenance)),
    )
    if not signal.segments:
        return AnalysisNightSignalDetail(
            signal.record_id,
            session_record_id,
            signal.signal_kind,
            signal.unit,
            signal.representation.value,
            signal.value_semantics,
            AnalysisAvailability.UNAVAILABLE,
            None,
            None,
            None,
            None,
            None,
            (),
            (),
            0,
            0,
            0,
            0,
            0,
            None,
            source_ids,
            provenance_ids,
            ("signal_samples_unavailable",),
            ("The normalized signal record contains no stored segment to preview.",),
        )
    selected = signal.segments[0]
    displayed = min(len(selected.values), ANALYSIS_NIGHT_SIGNAL_PREVIEW_MAX_SAMPLES)
    omitted = source_sample_count - displayed
    limitations = ["Display preview only; the first source segment was selected deterministically, not for clinical importance."]
    if omitted:
        limitations.append("Additional source samples or segments are intentionally omitted from this bounded browser response.")
    return AnalysisNightSignalDetail(
        signal.record_id,
        session_record_id,
        signal.signal_kind,
        signal.unit,
        signal.representation.value,
        signal.value_semantics,
        AnalysisAvailability.AVAILABLE,
        selected.record_id,
        selected.start_time_ms,
        selected.end_time_ms,
        selected.interval_closure.value,
        selected.sample_interval_ms,
        selected.sample_times_ms[:displayed],
        selected.values[:displayed],
        segment_count,
        source_sample_count,
        displayed,
        max(0, segment_count - 1),
        omitted,
        ANALYSIS_NIGHT_SIGNAL_PREVIEW_SELECTION,
        source_ids,
        provenance_ids,
        (),
        tuple(limitations),
    )


def _quality_detail(
    report_id: str,
    report_kind: str,
    session_record_id: str | None,
    finding: QualityFinding,
) -> AnalysisNightQualityFindingDetail:
    return AnalysisNightQualityFindingDetail(
        finding.record_id,
        report_id,
        report_kind,
        session_record_id,
        finding.rule_id.value,
        finding.status.value,
        finding.impact.value,
        finding.reason_code,
        finding.evaluated_record_id,
        finding.start_time_ms,
        finding.end_time_ms,
        tuple((value.name, value.value, value.unit) for value in finding.parameters),
        tuple((value.name, value.value, value.unit) for value in finding.measurements),
        finding.affected_capabilities,
        _sorted_texts(report_id, finding.record_id, finding.source_record_ids),
        finding.source_provenance_ids,
        finding.limitations,
    )


def _quality_availability(
    findings: tuple[AnalysisNightQualityFindingDetail, ...],
    report_ids: tuple[str, ...],
) -> tuple[AnalysisAvailability, tuple[str, ...]]:
    if not report_ids:
        return AnalysisAvailability.UNAVAILABLE, ("quality_not_evaluated",)
    if not findings:
        return AnalysisAvailability.NOT_EVALUABLE, ("quality_report_has_no_findings",)
    insufficient = tuple(value for value in findings if value.status == QualityStatus.INSUFFICIENT_EVIDENCE.value)
    reasons = tuple(sorted({f"{value.rule_id}:{value.status}:{value.reason_code}" for value in findings if value.status != QualityStatus.PASS.value}))
    if len(insufficient) == len(findings):
        return AnalysisAvailability.NOT_EVALUABLE, reasons
    if insufficient:
        return AnalysisAvailability.PARTIAL, reasons
    return AnalysisAvailability.AVAILABLE, reasons


def _collection_availability(states: tuple[AnalysisAvailability, ...]) -> AnalysisAvailability:
    if not states:
        return AnalysisAvailability.UNAVAILABLE
    if all(value is AnalysisAvailability.AVAILABLE for value in states):
        return AnalysisAvailability.AVAILABLE
    if all(value is AnalysisAvailability.UNAVAILABLE for value in states):
        return AnalysisAvailability.UNAVAILABLE
    return AnalysisAvailability.PARTIAL


def _provenance_detail(provenance: ProvenanceRecord) -> AnalysisNightProvenanceDetail:
    return AnalysisNightProvenanceDetail(
        provenance.record_id,
        tuple(value.value for value in provenance.source_classes),
        provenance.source_system,
        provenance.source_system_version,
        provenance.source_schema_version,
        provenance.producer,
        provenance.producer_version,
        provenance.parent_provenance_ids,
        tuple((value.source_record_type, value.source_record_id) for value in provenance.source_references),
    )


def _provenance_ids(provenance: ProvenanceRecord) -> tuple[str, ...]:
    return _sorted_texts(provenance.record_id, provenance.parent_provenance_ids)


def _typed_tuple(value: object, expected: type, label: str) -> tuple:
    if type(value) is not tuple or any(not isinstance(item, expected) for item in value):
        raise AnalysisNightDetailCompositionError(f"The {label} must be a tuple of {expected.__name__} records.")
    return value


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise AnalysisNightDetailCompositionError(f"The {label} must be unique.")


def _sorted_texts(*values: object) -> tuple[str, ...]:
    flattened: list[str] = []
    for value in values:
        if type(value) is str:
            flattened.append(value)
        elif isinstance(value, Iterable):
            flattened.extend(value)
        else:
            raise AnalysisNightDetailCompositionError("Night-detail source identifiers must be text or iterable text collections.")
    if any(type(value) is not str or not value.strip() for value in flattened):
        raise AnalysisNightDetailCompositionError("Night-detail source identifiers must be nonempty text.")
    return tuple(sorted(set(flattened)))
