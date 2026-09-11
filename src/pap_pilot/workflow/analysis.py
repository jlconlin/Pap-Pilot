"""Compose existing deterministic PAP records into the generic analysis workspace."""

from dataclasses import dataclass
import hashlib
from typing import Final, Iterable

from pap_pilot.engine.analysis import (
    AnalysisAvailability,
    AnalysisEvidence,
    AnalysisEvidenceKind,
    AnalysisExperimentReference,
    AnalysisNight,
    AnalysisResource,
    AnalysisResourceKind,
    AnalysisTrend,
    AnalysisTrendPoint,
    AnalysisWorkspace,
    analysis_resource_id,
)
from pap_pilot.engine.experiments import SleepJournalEntry
from pap_pilot.engine.metrics import MetricId, MetricResult, MetricStatus
from pap_pilot.engine.model import NightRecord, ProvenanceRecord, SignalRecord
from pap_pilot.engine.quality import QualityStatus, SignalQualityReport, StructuralQualityReport


ANALYSIS_WORKSPACE_TITLE: Final = "PAP analysis"
ANALYSIS_WORKSPACE_LIMITATIONS: Final = (
    "Analysis is advisory and does not change PAP-device settings.",
    "Missing data remains unavailable and is never converted to zero or imputed.",
)
_METRIC_LABELS: Final = {
    MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP: "Mean Mask Pressure above EPAP",
    MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO: "Minute ventilation upper-tail ratio",
}
_METRIC_UNITS: Final = {
    MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP: "cm H₂O",
    MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO: "1",
}


class AnalysisCompositionError(ValueError):
    """Raised when existing records cannot be linked without guessing."""


@dataclass(frozen=True, slots=True)
class _NightContext:
    night: NightRecord
    session_ids: tuple[str, ...]
    setting_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    signal_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    provenance_ids: tuple[str, ...]


def compose_analysis_workspace(
    nights: tuple[NightRecord, ...],
    *,
    structural_quality_reports: tuple[StructuralQualityReport, ...] = (),
    signal_quality_reports: tuple[SignalQualityReport, ...] = (),
    metric_results: tuple[MetricResult, ...] = (),
    journal_entries: tuple[SleepJournalEntry, ...] = (),
    experiments: tuple[AnalysisExperimentReference, ...] = (),
) -> AnalysisWorkspace:
    """Build one generic workspace from already-selected, already-evaluated records."""

    selected_nights = tuple(sorted(_typed_tuple(nights, NightRecord, "normalized nights"), key=lambda value: (value.local_date, value.record_id)))
    structural = tuple(sorted(_typed_tuple(structural_quality_reports, StructuralQualityReport, "structural quality reports"), key=lambda value: value.record_id))
    signal_quality = tuple(sorted(_typed_tuple(signal_quality_reports, SignalQualityReport, "signal quality reports"), key=lambda value: value.record_id))
    metrics = tuple(sorted(_typed_tuple(metric_results, MetricResult, "metric results"), key=lambda value: (value.night_record_id, value.metric_id.value, value.record_id)))
    journals = tuple(sorted(_typed_tuple(journal_entries, SleepJournalEntry, "journal entries"), key=lambda value: (value.night_record_id, value.record_id)))
    experiment_references = tuple(sorted(_typed_tuple(experiments, AnalysisExperimentReference, "analysis experiment references"), key=lambda value: value.experiment_record_id))
    _unique(tuple(value.record_id for value in selected_nights), "normalized night identifiers")
    _unique(tuple(value.record_id for value in structural), "structural quality report identifiers")
    _unique(tuple(value.record_id for value in signal_quality), "signal quality report identifiers")
    quality_report_ids = tuple(value.record_id for value in (*structural, *signal_quality))
    _unique(quality_report_ids, "quality report identifiers")
    _unique(tuple(value.record_id for value in metrics), "metric result identifiers")
    _unique(tuple(value.record_id for value in journals), "journal entry identifiers")

    contexts = tuple(_night_context(night) for night in selected_nights)
    context_by_night = {value.night.record_id: value for value in contexts}
    night_by_session = {
        session.record_id: context
        for context in contexts
        for session in context.night.sessions
    }
    if len(night_by_session) != sum(len(value.night.sessions) for value in contexts):
        raise AnalysisCompositionError("Session identifiers must be unique across analysis nights.")
    if any(value.night_record_id not in context_by_night for value in structural):
        raise AnalysisCompositionError("Every structural quality report must resolve to an analysis night.")
    if any(value.session_record_id not in night_by_session for value in signal_quality):
        raise AnalysisCompositionError("Every signal quality report must resolve to an analysis session.")
    if any(value.night_record_id not in context_by_night for value in metrics):
        raise AnalysisCompositionError("Every metric result must resolve to an analysis night.")
    if any(not set(value.session_record_ids).issubset(context_by_night[value.night_record_id].session_ids) for value in metrics):
        raise AnalysisCompositionError("Every metric session must resolve within its analysis night.")
    if any(not set(value.setting_record_ids).issubset(context_by_night[value.night_record_id].setting_ids) for value in metrics):
        raise AnalysisCompositionError("Every metric setting must resolve within its analysis night.")
    if any(not set(value.quality_report_ids).issubset(quality_report_ids) for value in metrics):
        raise AnalysisCompositionError("Every metric quality report must resolve in the supplied quality evidence.")
    if any(value.night_record_id not in context_by_night for value in journals):
        raise AnalysisCompositionError("Every journal entry must resolve to an analysis night.")
    _unique(tuple((value.night_record_id, value.metric_id) for value in metrics), "per-night metric results")

    structural_by_night = {
        night.record_id: tuple(value for value in structural if value.night_record_id == night.record_id)
        for night in selected_nights
    }
    signal_quality_by_night = {
        night.record_id: tuple(value for value in signal_quality if night_by_session[value.session_record_id].night.record_id == night.record_id)
        for night in selected_nights
    }
    metrics_by_night = {
        night.record_id: tuple(value for value in metrics if value.night_record_id == night.record_id)
        for night in selected_nights
    }
    journals_by_night = {
        night.record_id: tuple(value for value in journals if value.night_record_id == night.record_id)
        for night in selected_nights
    }

    evidence = []
    analysis_nights = []
    for context in contexts:
        night_evidence = [
            _settings_evidence(context),
            _events_evidence(context),
            *(_signal_evidence(context, session.record_id, signal) for session in context.night.sessions for signal in session.signals),
        ]
        quality_reports = (*structural_by_night[context.night.record_id], *signal_quality_by_night[context.night.record_id])
        if quality_reports:
            night_evidence.extend(_quality_evidence(context, report) for report in quality_reports)
        else:
            night_evidence.append(_missing_evidence(context, AnalysisEvidenceKind.QUALITY, "Data quality", "quality_not_evaluated"))
        night_metrics = metrics_by_night[context.night.record_id]
        night_evidence.extend(_metric_evidence(value) for value in night_metrics)
        night_journals = journals_by_night[context.night.record_id]
        if night_journals:
            night_evidence.extend(_journal_evidence(value) for value in night_journals)
        else:
            night_evidence.append(_missing_evidence(context, AnalysisEvidenceKind.JOURNAL, "Morning journal", "journal_not_reported"))

        quality_ids = tuple(value.record_id for value in quality_reports)
        metric_ids = tuple(value.record_id for value in night_metrics)
        journal_ids = tuple(value.record_id for value in night_journals)
        sources = _sorted_texts(
            context.source_ids,
            quality_ids,
            *(finding.record_id for report in quality_reports for finding in report.findings),
            metric_ids,
            journal_ids,
        )
        provenance = _sorted_texts(
            context.provenance_ids,
            *(identifier for report in quality_reports for finding in report.findings for identifier in finding.source_provenance_ids),
            *(identifier for value in night_metrics for identifier in value.source_provenance_ids),
            *(identifier for value in night_journals for identifier in value.source_provenance_ids),
        )
        complete = all(value.availability is AnalysisAvailability.AVAILABLE for value in night_evidence)
        analysis_nights.append(
            AnalysisNight(
                record_id=f"analysis-night:{context.night.record_id}",
                night_record_id=context.night.record_id,
                local_date=context.night.local_date,
                availability=AnalysisAvailability.AVAILABLE if complete else AnalysisAvailability.PARTIAL,
                session_record_ids=context.session_ids,
                setting_record_ids=context.setting_ids,
                event_record_ids=context.event_ids,
                signal_record_ids=context.signal_ids,
                quality_report_ids=quality_ids,
                metric_result_ids=metric_ids,
                journal_entry_ids=journal_ids,
                evidence_record_ids=tuple(value.record_id for value in night_evidence),
                source_record_ids=sources,
                source_provenance_ids=provenance,
                reason_codes=() if complete else ("one_or_more_evidence_items_unavailable",),
                limitations=("Night availability describes retained evidence, not therapy effectiveness or clinical safety.",),
            )
        )
        evidence.extend(night_evidence)

    trends = _metric_trends(selected_nights, metrics)
    if not selected_nights:
        workspace_availability = AnalysisAvailability.UNAVAILABLE
        workspace_reasons = ("no_therapy_nights",)
    else:
        workspace_reasons = tuple(
            reason
            for condition, reason in (
                (any(value.availability is not AnalysisAvailability.AVAILABLE for value in analysis_nights), "one_or_more_nights_partial"),
                (not trends, "no_trend_series"),
                (any(value.availability is not AnalysisAvailability.AVAILABLE for value in trends), "one_or_more_trends_incomplete"),
            )
            if condition
        )
        workspace_availability = AnalysisAvailability.AVAILABLE if not workspace_reasons else AnalysisAvailability.PARTIAL

    workspace_sources = _sorted_texts(
        *(identifier for value in analysis_nights for identifier in value.source_record_ids),
        *(identifier for value in trends for identifier in value.source_record_ids),
        *(identifier for value in evidence for identifier in value.source_record_ids),
        *(identifier for value in experiment_references for identifier in value.source_record_ids),
    )
    workspace_provenance = _sorted_texts(
        *(identifier for value in analysis_nights for identifier in value.source_provenance_ids),
        *(identifier for value in trends for identifier in value.source_provenance_ids),
        *(identifier for value in evidence for identifier in value.source_provenance_ids),
        *(identifier for value in experiment_references for identifier in value.source_provenance_ids),
    )
    identity = repr(
        (
            tuple(value.record_id for value in analysis_nights),
            tuple(value.record_id for value in trends),
            tuple(value.record_id for value in evidence),
            tuple(value.experiment_record_id for value in experiment_references),
            workspace_availability.value,
            workspace_reasons,
        )
    )
    workspace_id = f"analysis-workspace:{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
    resources = _resources(
        workspace_id,
        workspace_availability,
        workspace_reasons,
        tuple(analysis_nights),
        trends,
        tuple(evidence),
        experiment_references,
    )
    return AnalysisWorkspace(
        record_id=workspace_id,
        title=ANALYSIS_WORKSPACE_TITLE,
        availability=workspace_availability,
        nights=tuple(analysis_nights),
        trends=trends,
        evidence=tuple(evidence),
        resources=resources,
        experiments=experiment_references,
        source_record_ids=workspace_sources,
        source_provenance_ids=workspace_provenance,
        reason_codes=workspace_reasons,
        limitations=ANALYSIS_WORKSPACE_LIMITATIONS,
    )


def unavailable_analysis_workspace(reason_code: str = "analysis_workspace_not_configured") -> AnalysisWorkspace:
    """Return an explicit empty API root without implying that OSCAR was queried."""

    if type(reason_code) is not str or not reason_code.strip():
        raise AnalysisCompositionError("An unavailable analysis workspace requires a reason code.")
    workspace_id = "analysis-workspace:unavailable"
    resources = tuple(
        AnalysisResource(
            resource_id=analysis_resource_id(kind, workspace_id),
            kind=kind,
            target_record_id=workspace_id,
            availability=AnalysisAvailability.UNAVAILABLE,
            reason_codes=(reason_code,),
        )
        for kind in (AnalysisResourceKind.OVERVIEW, AnalysisResourceKind.NIGHT_COLLECTION, AnalysisResourceKind.TREND_COLLECTION)
    )
    return AnalysisWorkspace(
        record_id=workspace_id,
        title=ANALYSIS_WORKSPACE_TITLE,
        availability=AnalysisAvailability.UNAVAILABLE,
        nights=(),
        trends=(),
        evidence=(),
        resources=resources,
        experiments=(),
        source_record_ids=(),
        source_provenance_ids=(),
        reason_codes=(reason_code,),
        limitations=ANALYSIS_WORKSPACE_LIMITATIONS,
    )


def _night_context(night: NightRecord) -> _NightContext:
    sessions = night.sessions
    settings = tuple(value for session in sessions for value in session.settings)
    events = tuple(value for session in sessions for value in session.events)
    signals = tuple(value for session in sessions for value in session.signals)
    segments = tuple(value for signal in signals for value in signal.segments)
    records = (night, *sessions, *settings, *events, *signals, *segments)
    return _NightContext(
        night=night,
        session_ids=tuple(value.record_id for value in sessions),
        setting_ids=tuple(value.record_id for value in settings),
        event_ids=tuple(value.record_id for value in events),
        signal_ids=tuple(value.record_id for value in signals),
        source_ids=_sorted_texts(*(value.record_id for value in records)),
        provenance_ids=_sorted_texts(*(identifier for value in records for identifier in _provenance_ids(value.provenance))),
    )


def _settings_evidence(context: _NightContext) -> AnalysisEvidence:
    available = bool(context.setting_ids)
    return AnalysisEvidence(
        record_id=f"analysis-evidence:settings:{context.night.record_id}",
        kind=AnalysisEvidenceKind.SETTING,
        label="Therapy settings",
        availability=AnalysisAvailability.AVAILABLE if available else AnalysisAvailability.UNAVAILABLE,
        night_record_ids=(context.night.record_id,),
        session_record_ids=context.session_ids,
        source_record_ids=context.setting_ids if available else (context.night.record_id, *context.session_ids),
        source_provenance_ids=_sorted_texts(
            *(identifier for session in context.night.sessions for setting in session.settings for identifier in _provenance_ids(setting.provenance)),
            *(() if available else context.provenance_ids),
        ),
        reason_codes=() if available else ("settings_unavailable",),
        limitations=("Settings are observations from the normalized source and are never changed by PAP Pilot.",),
    )


def _events_evidence(context: _NightContext) -> AnalysisEvidence:
    events = tuple(value for session in context.night.sessions for value in session.events)
    available = bool(events)
    return AnalysisEvidence(
        record_id=f"analysis-evidence:events:{context.night.record_id}",
        kind=AnalysisEvidenceKind.EVENT,
        label="Machine-labeled respiratory events",
        availability=AnalysisAvailability.AVAILABLE if available else AnalysisAvailability.UNAVAILABLE,
        night_record_ids=(context.night.record_id,),
        session_record_ids=context.session_ids,
        source_record_ids=tuple(value.record_id for value in events) if available else (context.night.record_id, *context.session_ids),
        source_provenance_ids=_sorted_texts(
            *(identifier for value in events for identifier in _provenance_ids(value.provenance)),
            *(() if available else context.provenance_ids),
        ),
        reason_codes=() if available else ("no_normalized_event_records",),
        limitations=("Machine-labeled events are reference evidence; absence and completeness are not inferred.",),
    )


def _signal_evidence(context: _NightContext, session_record_id: str, signal: SignalRecord) -> AnalysisEvidence:
    segments = signal.segments
    available = bool(segments)
    return AnalysisEvidence(
        record_id=f"analysis-evidence:signal:{signal.record_id}",
        kind=AnalysisEvidenceKind.SIGNAL,
        label=signal.signal_kind.replace("_", " ").title(),
        availability=AnalysisAvailability.AVAILABLE if available else AnalysisAvailability.UNAVAILABLE,
        night_record_ids=(context.night.record_id,),
        session_record_ids=(session_record_id,),
        source_record_ids=(signal.record_id, *(value.record_id for value in segments)),
        source_provenance_ids=_sorted_texts(
            *_provenance_ids(signal.provenance),
            *(identifier for value in segments for identifier in _provenance_ids(value.provenance)),
        ),
        reason_codes=() if available else ("signal_samples_unavailable",),
        limitations=("Signal gaps remain explicit; this inventory does not interpolate or infer waveform values.",),
    )


def _quality_evidence(context: _NightContext, report: StructuralQualityReport | SignalQualityReport) -> AnalysisEvidence:
    session_ids = () if isinstance(report, StructuralQualityReport) else (report.session_record_id,)
    insufficient = tuple(value for value in report.findings if value.status is QualityStatus.INSUFFICIENT_EVIDENCE)
    if not report.findings:
        availability = AnalysisAvailability.NOT_EVALUABLE
        reason_codes = ("quality_report_has_no_findings",)
    elif len(insufficient) == len(report.findings):
        availability = AnalysisAvailability.NOT_EVALUABLE
        reason_codes = _quality_reason_codes(report)
    elif insufficient:
        availability = AnalysisAvailability.PARTIAL
        reason_codes = _quality_reason_codes(report)
    else:
        availability = AnalysisAvailability.AVAILABLE
        reason_codes = _quality_reason_codes(report)
    sources = _sorted_texts(
        report.record_id,
        *(value.record_id for value in report.findings),
        *(identifier for value in report.findings for identifier in value.source_record_ids),
    )
    provenance = _sorted_texts(*(identifier for value in report.findings for identifier in value.source_provenance_ids))
    return AnalysisEvidence(
        record_id=f"analysis-evidence:quality:{report.record_id}",
        kind=AnalysisEvidenceKind.QUALITY,
        label="Structural data quality" if isinstance(report, StructuralQualityReport) else "Signal data quality",
        availability=availability,
        night_record_ids=(context.night.record_id,),
        session_record_ids=session_ids,
        source_record_ids=sources,
        source_provenance_ids=provenance,
        reason_codes=reason_codes,
        limitations=_sorted_texts(*(value for finding in report.findings for value in finding.limitations)),
    )


def _quality_reason_codes(report: StructuralQualityReport | SignalQualityReport) -> tuple[str, ...]:
    return _sorted_texts(*(f"{value.rule_id.value}:{value.status.value}:{value.reason_code}" for value in report.findings))


def _metric_evidence(result: MetricResult) -> AnalysisEvidence:
    available = result.status is MetricStatus.CALCULATED
    return AnalysisEvidence(
        record_id=f"analysis-evidence:metric:{result.record_id}",
        kind=AnalysisEvidenceKind.METRIC,
        label=_METRIC_LABELS[result.metric_id],
        availability=AnalysisAvailability.AVAILABLE if available else AnalysisAvailability.NOT_EVALUABLE,
        night_record_ids=(result.night_record_id,),
        session_record_ids=result.session_record_ids,
        source_record_ids=_sorted_texts(result.record_id, result.source_record_ids, result.quality_report_ids, result.quality_finding_ids),
        source_provenance_ids=result.source_provenance_ids,
        reason_codes=() if available else (result.reason_code.value,),
        limitations=result.limitations,
    )


def _journal_evidence(entry: SleepJournalEntry) -> AnalysisEvidence:
    return AnalysisEvidence(
        record_id=f"analysis-evidence:journal:{entry.record_id}",
        kind=AnalysisEvidenceKind.JOURNAL,
        label="Morning journal",
        availability=AnalysisAvailability.AVAILABLE,
        night_record_ids=(entry.night_record_id,),
        session_record_ids=(),
        source_record_ids=(entry.night_record_id, entry.record_id),
        source_provenance_ids=entry.source_provenance_ids,
        limitations=("Journal observations are user-reported and are not inferred from PAP signals.",),
    )


def _missing_evidence(context: _NightContext, kind: AnalysisEvidenceKind, label: str, reason: str) -> AnalysisEvidence:
    return AnalysisEvidence(
        record_id=f"analysis-evidence:{kind.value}:{context.night.record_id}:unavailable",
        kind=kind,
        label=label,
        availability=AnalysisAvailability.UNAVAILABLE,
        night_record_ids=(context.night.record_id,),
        session_record_ids=context.session_ids,
        source_record_ids=(context.night.record_id, *context.session_ids),
        source_provenance_ids=context.provenance_ids,
        reason_codes=(reason,),
    )


def _metric_trends(nights: tuple[NightRecord, ...], metrics: tuple[MetricResult, ...]) -> tuple[AnalysisTrend, ...]:
    result_by_key = {(value.night_record_id, value.metric_id): value for value in metrics}
    values = []
    for metric_id in sorted({value.metric_id for value in metrics}, key=lambda value: value.value):
        points = []
        for night in nights:
            result = result_by_key.get((night.record_id, metric_id))
            if result is None:
                points.append(AnalysisTrendPoint(night.record_id, night.local_date, None, AnalysisAvailability.UNAVAILABLE, (), (), ("metric_not_calculated",)))
            elif result.status is MetricStatus.CALCULATED:
                points.append(AnalysisTrendPoint(night.record_id, night.local_date, result.value, AnalysisAvailability.AVAILABLE, _sorted_texts(result.record_id, result.source_record_ids), result.source_provenance_ids))
            else:
                points.append(AnalysisTrendPoint(night.record_id, night.local_date, None, AnalysisAvailability.NOT_EVALUABLE, _sorted_texts(result.record_id, result.source_record_ids), result.source_provenance_ids, (result.reason_code.value,)))
        states = {value.availability for value in points}
        if states == {AnalysisAvailability.AVAILABLE}:
            availability = AnalysisAvailability.AVAILABLE
            reasons = ()
        elif states == {AnalysisAvailability.NOT_EVALUABLE}:
            availability = AnalysisAvailability.NOT_EVALUABLE
            reasons = ("metric_not_evaluable_for_any_night",)
        elif states == {AnalysisAvailability.UNAVAILABLE}:
            availability = AnalysisAvailability.UNAVAILABLE
            reasons = ("metric_not_calculated_for_any_night",)
        else:
            availability = AnalysisAvailability.PARTIAL
            reasons = ("one_or_more_points_unavailable",)
        values.append(
            AnalysisTrend(
                record_id=f"analysis-trend:{metric_id.value}",
                metric_id=metric_id.value,
                label=_METRIC_LABELS[metric_id],
                unit=_METRIC_UNITS[metric_id],
                availability=availability,
                points=tuple(points),
                source_record_ids=_sorted_texts(*(identifier for point in points for identifier in point.source_record_ids)),
                source_provenance_ids=_sorted_texts(*(identifier for point in points for identifier in point.source_provenance_ids)),
                reason_codes=reasons,
                limitations=("The trend exposes an existing deterministic metric and does not add a new analytical method.",),
            )
        )
    return tuple(values)


def _resources(
    workspace_id: str,
    workspace_availability: AnalysisAvailability,
    workspace_reasons: tuple[str, ...],
    nights: tuple[AnalysisNight, ...],
    trends: tuple[AnalysisTrend, ...],
    evidence: tuple[AnalysisEvidence, ...],
    experiments: tuple[AnalysisExperimentReference, ...],
) -> tuple[AnalysisResource, ...]:
    values = [
        AnalysisResource(analysis_resource_id(AnalysisResourceKind.OVERVIEW, workspace_id), AnalysisResourceKind.OVERVIEW, workspace_id, workspace_availability, workspace_reasons),
        AnalysisResource(
            analysis_resource_id(AnalysisResourceKind.NIGHT_COLLECTION, workspace_id),
            AnalysisResourceKind.NIGHT_COLLECTION,
            workspace_id,
            _collection_availability(tuple(value.availability for value in nights)),
            () if nights and all(value.availability is AnalysisAvailability.AVAILABLE for value in nights) else (("no_therapy_nights",) if not nights else ("one_or_more_nights_partial",)),
        ),
    ]
    values.append(AnalysisResource(
        analysis_resource_id(AnalysisResourceKind.TREND_COLLECTION, workspace_id),
        AnalysisResourceKind.TREND_COLLECTION,
        workspace_id,
        _collection_availability(tuple(value.availability for value in trends)),
        () if trends and all(value.availability is AnalysisAvailability.AVAILABLE for value in trends) else (("no_trend_series",) if not trends else ("one_or_more_trends_incomplete",)),
    ))
    values.extend(AnalysisResource(analysis_resource_id(AnalysisResourceKind.NIGHT_DETAIL, value.night_record_id), AnalysisResourceKind.NIGHT_DETAIL, value.night_record_id, value.availability, value.reason_codes) for value in nights)
    values.extend(AnalysisResource(analysis_resource_id(AnalysisResourceKind.TREND_DETAIL, value.record_id), AnalysisResourceKind.TREND_DETAIL, value.record_id, value.availability, value.reason_codes) for value in trends)
    values.extend(AnalysisResource(analysis_resource_id(AnalysisResourceKind.EVIDENCE, value.record_id), AnalysisResourceKind.EVIDENCE, value.record_id, value.availability, value.reason_codes) for value in evidence)
    values.extend(AnalysisResource(value.resource_id, AnalysisResourceKind.EXPERIMENT, value.experiment_record_id, value.availability, value.reason_codes) for value in experiments)
    return tuple(values)


def _collection_availability(states: tuple[AnalysisAvailability, ...]) -> AnalysisAvailability:
    if not states:
        return AnalysisAvailability.UNAVAILABLE
    unique = set(states)
    if unique == {AnalysisAvailability.AVAILABLE}:
        return AnalysisAvailability.AVAILABLE
    if unique == {AnalysisAvailability.UNAVAILABLE}:
        return AnalysisAvailability.UNAVAILABLE
    if unique == {AnalysisAvailability.NOT_EVALUABLE}:
        return AnalysisAvailability.NOT_EVALUABLE
    return AnalysisAvailability.PARTIAL


def _provenance_ids(provenance: ProvenanceRecord) -> tuple[str, ...]:
    return _sorted_texts(provenance.record_id, provenance.parent_provenance_ids)


def _typed_tuple(value: object, expected: type, label: str) -> tuple:
    if type(value) is not tuple or any(not isinstance(item, expected) for item in value):
        raise AnalysisCompositionError(f"The {label} must be a tuple of {expected.__name__} records.")
    return value


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise AnalysisCompositionError(f"The {label} must be unique.")


def _sorted_texts(*values: object) -> tuple[str, ...]:
    flattened: list[str] = []
    for value in values:
        if type(value) is str:
            flattened.append(value)
        elif isinstance(value, Iterable):
            flattened.extend(value)
        else:
            raise AnalysisCompositionError("Analysis source identifiers must be text or iterable text collections.")
    if any(type(value) is not str or not value.strip() for value in flattened):
        raise AnalysisCompositionError("Analysis source identifiers must be nonempty text.")
    return tuple(sorted(set(flattened)))
