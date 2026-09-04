"""Deterministically orchestrate one selected retrospective evaluation."""

from dataclasses import dataclass
import hashlib
from typing import Final

from pap_pilot.engine.experiments.allocation import (
    ExperimentNightAllocation,
    allocate_experiment_nights,
)
from pap_pilot.engine.experiments.classification import (
    OutcomeClassificationResult,
    evaluate_outcome_classification,
)
from pap_pilot.engine.experiments.journal import (
    RetrospectiveNightEvidence,
    SleepJournalEntry,
)
from pap_pilot.engine.experiments.model import (
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentProposedPayload,
    SettingChangeConfirmedPayload,
)
from pap_pilot.engine.experiments.retrospective_protocol import (
    RetrospectiveCohortEvidence,
)
from pap_pilot.engine.experiments.storage import ReplayedExperiment
from pap_pilot.engine.metrics import (
    MetricId,
    MetricResult,
    evaluate_mean_mask_pressure_above_epap,
    evaluate_minute_ventilation_upper_tail_ratio,
)
from pap_pilot.engine.model import NightRecord, ProvenanceRecord, SourceClass
from pap_pilot.engine.quality import (
    ClockCorrectionEvidence,
    SignalQualityReport,
    StructuralQualityReport,
    TimeBasis,
    evaluate_signal_quality,
    evaluate_structural_quality,
)


RETROSPECTIVE_EVALUATION_SCHEMA_ID: Final = "pap-pilot.retrospective-evaluation"
RETROSPECTIVE_EVALUATION_SCHEMA_VERSION: Final = 1
RETROSPECTIVE_EVALUATION_RECORD_VERSION: Final = 1
RETROSPECTIVE_EVALUATION_ENGINE_VERSION: Final = "0.1.0"
_ALL_REQUIRED_SIGNALS: Final = ("flow_rate", "leak_rate", "mask_pressure")
_VENTILATION_REQUIRED_SIGNALS: Final = ("flow_rate", "leak_rate")
_USER_EVIDENCE_EVENT_TYPES: Final = frozenset(
    {
        ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED,
        ExperimentEventType.CONFOUNDER_RECORDED,
        ExperimentEventType.ADVERSE_EFFECT_RECORDED,
    }
)


class RetrospectiveEvaluationError(ValueError):
    """Raised when a selected retrospective evaluation cannot be linked exactly."""


@dataclass(frozen=True, slots=True)
class RetrospectiveSessionClockEvidence:
    """Source-independent correction evidence for one selected normalized session."""

    session_record_id: str
    evidence: ClockCorrectionEvidence
    record_version: int = RETROSPECTIVE_EVALUATION_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.session_record_id, "retrospective clock-evidence session identifier")
        if not isinstance(self.evidence, ClockCorrectionEvidence):
            raise RetrospectiveEvaluationError(
                "Retrospective session clock evidence requires a quality-layer correction record."
            )
        if self.record_version != RETROSPECTIVE_EVALUATION_RECORD_VERSION:
            raise RetrospectiveEvaluationError(
                "The retrospective session clock-evidence version is unsupported."
            )


@dataclass(frozen=True, slots=True)
class RetrospectiveEvaluationBundle:
    """One immutable, fully linked result of the version-1 retrospective pipeline."""

    record_id: str
    experiment_record_id: str
    cohort_record_id: str
    selected_nights: tuple[NightRecord, ...]
    session_clock_evidence: tuple[RetrospectiveSessionClockEvidence, ...]
    allocation_structural_quality_reports: tuple[StructuralQualityReport, ...]
    metric_structural_quality_reports: tuple[StructuralQualityReport, ...]
    signal_quality_reports: tuple[SignalQualityReport, ...]
    allocation: ExperimentNightAllocation
    metric_results: tuple[MetricResult, ...]
    retrospective_night_evidence: tuple[RetrospectiveNightEvidence, ...]
    effective_journal_entries: tuple[SleepJournalEntry, ...]
    effective_events: tuple[ExperimentEvent, ...]
    classification: OutcomeClassificationResult
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    schema_id: str = RETROSPECTIVE_EVALUATION_SCHEMA_ID
    schema_version: int = RETROSPECTIVE_EVALUATION_SCHEMA_VERSION
    record_version: int = RETROSPECTIVE_EVALUATION_RECORD_VERSION
    engine_version: str = RETROSPECTIVE_EVALUATION_ENGINE_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.record_id, "retrospective evaluation identifier"),
            (self.experiment_record_id, "retrospective evaluation experiment identifier"),
            (self.cohort_record_id, "retrospective evaluation cohort identifier"),
        ):
            _text(value, label)
        nights = _typed_tuple(self.selected_nights, NightRecord, "selected retrospective nights", required=True)
        clocks = _typed_tuple(
            self.session_clock_evidence,
            RetrospectiveSessionClockEvidence,
            "retrospective session clock evidence",
            required=True,
        )
        allocation_reports = _typed_tuple(
            self.allocation_structural_quality_reports,
            StructuralQualityReport,
            "allocation structural quality reports",
            required=True,
        )
        metric_reports = _typed_tuple(
            self.metric_structural_quality_reports,
            StructuralQualityReport,
            "metric structural quality reports",
            required=True,
        )
        signal_reports = _typed_tuple(
            self.signal_quality_reports,
            SignalQualityReport,
            "signal quality reports",
            required=True,
        )
        metrics = _typed_tuple(self.metric_results, MetricResult, "retrospective metric results", required=True)
        user_evidence = _typed_tuple(
            self.retrospective_night_evidence,
            RetrospectiveNightEvidence,
            "retrospective night evidence",
            required=True,
        )
        journals = _typed_tuple(self.effective_journal_entries, SleepJournalEntry, "effective journal entries")
        events = _typed_tuple(self.effective_events, ExperimentEvent, "effective experiment events", required=True)
        if not isinstance(self.allocation, ExperimentNightAllocation):
            raise RetrospectiveEvaluationError("A retrospective evaluation requires one night allocation.")
        if not isinstance(self.classification, OutcomeClassificationResult):
            raise RetrospectiveEvaluationError("A retrospective evaluation requires one outcome classification.")

        night_ids = tuple(night.record_id for night in nights)
        session_ids = tuple(session.record_id for night in nights for session in night.sessions)
        _unique(night_ids, "selected retrospective night identifiers")
        _unique(session_ids, "selected retrospective session identifiers")
        if tuple(value.session_record_id for value in clocks) != tuple(sorted(session_ids)):
            raise RetrospectiveEvaluationError(
                "Retrospective clock evidence must cover every selected session exactly once."
            )
        if tuple(report.night_record_id for report in allocation_reports) != night_ids:
            raise RetrospectiveEvaluationError(
                "Allocation quality must cover every selected night in cohort order."
            )
        if any(
            report.required_signal_kinds != _ALL_REQUIRED_SIGNALS
            or not report.require_flow_pressure_alignment
            or report.time_basis is not TimeBasis.CORRECTED_WALL_CLOCK
            for report in allocation_reports
        ):
            raise RetrospectiveEvaluationError(
                "Allocation quality must use the complete corrected-wall-clock version-1 request."
            )
        expected_metric_report_keys = tuple(
            key
            for night_id in night_ids
            for key in (
                (night_id, _ALL_REQUIRED_SIGNALS, True, TimeBasis.RAW_RELATIVE),
                (night_id, _VENTILATION_REQUIRED_SIGNALS, False, TimeBasis.RAW_RELATIVE),
            )
        )
        actual_metric_report_keys = tuple(
            (
                report.night_record_id,
                report.required_signal_kinds,
                report.require_flow_pressure_alignment,
                report.time_basis,
            )
            for report in metric_reports
        )
        if actual_metric_report_keys != expected_metric_report_keys:
            raise RetrospectiveEvaluationError(
                "Metric quality must retain both version-1 structural requests for every selected night."
            )
        if tuple(report.session_record_id for report in signal_reports) != session_ids:
            raise RetrospectiveEvaluationError(
                "Signal quality must cover every selected session in cohort order."
            )
        if any(report.breath_series_record_id is not None for report in signal_reports):
            raise RetrospectiveEvaluationError(
                "Version-1 retrospective orchestration cannot infer or invent breath-detector evidence."
            )
        if tuple(value.night_record_id for value in self.allocation.nights) != night_ids:
            raise RetrospectiveEvaluationError(
                "The experiment allocation must cover every selected night in cohort order."
            )
        expected_metric_keys = tuple(
            (night_id, metric_id)
            for night_id in night_ids
            for metric_id in (
                MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP,
                MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO,
            )
        )
        if tuple((result.night_record_id, result.metric_id) for result in metrics) != expected_metric_keys:
            raise RetrospectiveEvaluationError(
                "Both version-1 metrics must run once for every selected night."
            )
        if tuple(value.night_record_id for value in user_evidence) != night_ids:
            raise RetrospectiveEvaluationError(
                "Retrospective user evidence must cover every selected night in cohort order."
            )
        if any(
            value.experiment_record_id != self.experiment_record_id
            or value.cohort_record_id != self.cohort_record_id
            or value.cohort_night_index != index
            for index, value in enumerate(user_evidence)
        ):
            raise RetrospectiveEvaluationError(
                "Retrospective user evidence must link the evaluated experiment, cohort, and positions."
            )
        _unique(tuple(value.record_id for value in journals), "effective journal-entry identifiers")
        _unique(tuple(value.record_id for value in events), "effective experiment-event identifiers")

        all_reports = (*allocation_reports, *metric_reports, *signal_reports)
        report_ids = {report.record_id for report in all_reports}
        if len(report_ids) != len(all_reports):
            raise RetrospectiveEvaluationError(
                "Retrospective quality report identifiers must be unique across report roles."
            )
        findings = tuple(finding for report in all_reports for finding in report.findings)
        finding_ids = {finding.record_id for finding in findings}
        if not set(self.classification.quality_report_ids).issubset(report_ids):
            raise RetrospectiveEvaluationError(
                "Every quality report cited by the classification must resolve in the evaluation bundle."
            )
        if not set(self.classification.quality_finding_ids).issubset(finding_ids):
            raise RetrospectiveEvaluationError(
                "Every quality finding cited by the classification must resolve in the evaluation bundle."
            )
        if any(not set(result.quality_report_ids).issubset(report_ids) for result in metrics):
            raise RetrospectiveEvaluationError(
                "Every quality report cited by a metric must resolve in the evaluation bundle."
            )
        if any(not set(result.quality_finding_ids).issubset(finding_ids) for result in metrics):
            raise RetrospectiveEvaluationError(
                "Every quality finding cited by a metric must resolve in the evaluation bundle."
            )
        if self.classification.allocation_record_id != self.allocation.record_id:
            raise RetrospectiveEvaluationError(
                "The classification must reference the bundle's exact allocation."
            )
        if set(self.classification.metric_result_ids) != {result.record_id for result in metrics}:
            raise RetrospectiveEvaluationError(
                "The classification must reference every metric result in the bundle."
            )
        if set(self.classification.journal_entry_ids) != {entry.record_id for entry in journals}:
            raise RetrospectiveEvaluationError(
                "The classification must reference every effective journal entry in the bundle."
            )

        sources = _text_tuple(self.source_record_ids, "retrospective evaluation source identifiers", required=True)
        provenance = _text_tuple(
            self.source_provenance_ids,
            "retrospective evaluation provenance identifiers",
            required=True,
        )
        _unique(sources, "retrospective evaluation source identifiers")
        _unique(provenance, "retrospective evaluation provenance identifiers")
        required_sources = {
            self.experiment_record_id,
            self.cohort_record_id,
            *night_ids,
            *session_ids,
            *(value.record_id for value in user_evidence),
            *(value.record_id for value in journals),
            *(value.record_id for value in events),
            *(report.record_id for report in all_reports),
            *(finding.record_id for finding in findings),
            self.allocation.record_id,
            *(value.record_id for value in self.allocation.nights),
            *(value.record_id for value in metrics),
            self.classification.record_id,
        }
        if not required_sources.issubset(sources):
            raise RetrospectiveEvaluationError(
                "Evaluation provenance must reach every selected night, quality result, metric, user event, allocation, and classification."
            )
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise RetrospectiveEvaluationError(
                "Retrospective evaluation bundles must remain companion-derived."
            )
        if (
            self.schema_id,
            self.schema_version,
            self.record_version,
            self.engine_version,
        ) != (
            RETROSPECTIVE_EVALUATION_SCHEMA_ID,
            RETROSPECTIVE_EVALUATION_SCHEMA_VERSION,
            RETROSPECTIVE_EVALUATION_RECORD_VERSION,
            RETROSPECTIVE_EVALUATION_ENGINE_VERSION,
        ):
            raise RetrospectiveEvaluationError(
                "The retrospective evaluation schema, record, or engine version is unsupported."
            )

        object.__setattr__(self, "selected_nights", nights)
        object.__setattr__(self, "session_clock_evidence", clocks)
        object.__setattr__(self, "allocation_structural_quality_reports", allocation_reports)
        object.__setattr__(self, "metric_structural_quality_reports", metric_reports)
        object.__setattr__(self, "signal_quality_reports", signal_reports)
        object.__setattr__(self, "metric_results", metrics)
        object.__setattr__(self, "retrospective_night_evidence", user_evidence)
        object.__setattr__(self, "effective_journal_entries", journals)
        object.__setattr__(self, "effective_events", events)
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))
        object.__setattr__(self, "source_provenance_ids", tuple(sorted(provenance)))


def evaluate_retrospective_experiment(
    replayed: ReplayedExperiment,
    cohort: RetrospectiveCohortEvidence,
    session_clock_evidence: tuple[RetrospectiveSessionClockEvidence, ...],
) -> RetrospectiveEvaluationBundle:
    """Run the complete S37D deterministic pipeline from exact supplied evidence."""

    if not isinstance(replayed, ReplayedExperiment):
        raise RetrospectiveEvaluationError(
            "Retrospective evaluation requires a replayed experiment."
        )
    if not isinstance(cohort, RetrospectiveCohortEvidence):
        raise RetrospectiveEvaluationError(
            "Retrospective evaluation requires selected cohort evidence."
        )
    clocks = _typed_tuple(
        session_clock_evidence,
        RetrospectiveSessionClockEvidence,
        "retrospective session clock evidence",
        required=True,
    )
    sessions = tuple(session for night in cohort.nights for session in night.sessions)
    session_ids = {session.record_id for session in sessions}
    clock_by_session = {value.session_record_id: value for value in clocks}
    if len(clock_by_session) != len(clocks) or set(clock_by_session) != session_ids:
        raise RetrospectiveEvaluationError(
            "Retrospective clock evidence must cover every selected session exactly once and no other session."
        )
    clocks = tuple(sorted(clocks, key=lambda value: value.session_record_id))
    clock_by_session = {value.session_record_id: value for value in clocks}

    proposal = _one_effective_event(replayed, ExperimentEventType.EXPERIMENT_PROPOSED)
    acceptance = _one_effective_event(replayed, ExperimentEventType.EXPERIMENT_ACCEPTED)
    confirmation = _one_effective_event(
        replayed,
        ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED,
    )
    _validate_protocol_links(replayed, cohort, proposal, acceptance, confirmation)
    user_evidence, journals, evidence_events = _effective_user_evidence(
        replayed,
        cohort,
    )

    allocation_reports = tuple(
        evaluate_structural_quality(
            night,
            required_signal_kinds=_ALL_REQUIRED_SIGNALS,
            require_flow_pressure_alignment=True,
            time_basis=TimeBasis.CORRECTED_WALL_CLOCK,
            clock_corrections={
                session.record_id: clock_by_session[session.record_id].evidence
                for session in night.sessions
            },
        )
        for night in cohort.nights
    )
    signal_reports = tuple(
        evaluate_signal_quality(session, None)
        for night in cohort.nights
        for session in night.sessions
    )
    # The complete signal reports remain in the bundle and each metric applies its accepted signal-specific exclusions. Allocation consumes only the corrected structural request because missing breath-detector evidence blocks sleep/wake analysis, not these PAP-on metrics.
    allocation = allocate_experiment_nights(
        cohort.nights,
        confirmation,
        allocation_reports,
    )

    metric_reports = tuple(
        report
        for night in cohort.nights
        for report in (
            evaluate_structural_quality(
                night,
                required_signal_kinds=_ALL_REQUIRED_SIGNALS,
                require_flow_pressure_alignment=True,
                time_basis=TimeBasis.RAW_RELATIVE,
            ),
            evaluate_structural_quality(
                night,
                required_signal_kinds=_VENTILATION_REQUIRED_SIGNALS,
                require_flow_pressure_alignment=False,
                time_basis=TimeBasis.RAW_RELATIVE,
            ),
        )
    )
    metrics = tuple(
        result
        for night in cohort.nights
        for result in (
            evaluate_mean_mask_pressure_above_epap(night),
            evaluate_minute_ventilation_upper_tail_ratio(night),
        )
    )
    classification = evaluate_outcome_classification(
        proposal,
        acceptance,
        confirmation,
        allocation,
        metrics,
        journals,
        evidence_events,
        user_evidence,
    )

    all_reports = (*allocation_reports, *metric_reports, *signal_reports)
    findings = tuple(finding for report in all_reports for finding in report.findings)
    normalized_records, normalized_provenance = _normalized_inventory(cohort.nights)
    source_records = {
        replayed.experiment.record_id,
        cohort.record_id,
        *cohort.source_record_ids,
        *normalized_records,
        *(value.session_record_id for value in clocks),
        *(source for value in clocks for source in value.evidence.source_record_ids),
        *(event.record_id for event in replayed.effective_events),
        *(source for event in replayed.effective_events for source in event.source_record_ids),
        *(value.record_id for value in user_evidence),
        *(source for value in user_evidence for source in value.source_record_ids),
        *(entry.record_id for entry in journals),
        *(entry.night_record_id for entry in journals),
        *(report.record_id for report in all_reports),
        *(finding.record_id for finding in findings),
        *(source for finding in findings for source in finding.source_record_ids),
        allocation.record_id,
        *(value.record_id for value in allocation.nights),
        *(result.record_id for result in metrics),
        *(source for result in metrics for source in result.source_record_ids),
        classification.record_id,
        *classification.source_record_ids,
    }
    source_provenance = {
        *normalized_provenance,
        *(value for event in replayed.effective_events for value in event.source_provenance_ids),
        *(value for record in user_evidence for value in record.source_provenance_ids),
        *(value for entry in journals for value in entry.source_provenance_ids),
        *(value for finding in findings for value in finding.source_provenance_ids),
        *(value for result in metrics for value in result.source_provenance_ids),
        *classification.source_provenance_ids,
    }
    identity = (
        RETROSPECTIVE_EVALUATION_ENGINE_VERSION,
        replayed.experiment.record_id,
        cohort.record_id,
        tuple(night.record_id for night in cohort.nights),
        tuple(value.evidence for value in clocks),
        tuple(report.record_id for report in all_reports),
        allocation.record_id,
        tuple(result.record_id for result in metrics),
        tuple(value.record_id for value in user_evidence),
        tuple(event.record_id for event in replayed.effective_events),
        classification.record_id,
        tuple(sorted(source_records)),
        tuple(sorted(source_provenance)),
    )
    return RetrospectiveEvaluationBundle(
        record_id=f"retrospective-evaluation:{hashlib.sha256(repr(identity).encode()).hexdigest()[:20]}",
        experiment_record_id=replayed.experiment.record_id,
        cohort_record_id=cohort.record_id,
        selected_nights=cohort.nights,
        session_clock_evidence=clocks,
        allocation_structural_quality_reports=allocation_reports,
        metric_structural_quality_reports=metric_reports,
        signal_quality_reports=signal_reports,
        allocation=allocation,
        metric_results=metrics,
        retrospective_night_evidence=user_evidence,
        effective_journal_entries=journals,
        effective_events=replayed.effective_events,
        classification=classification,
        source_record_ids=tuple(source_records),
        source_provenance_ids=tuple(source_provenance),
    )


def _one_effective_event(
    replayed: ReplayedExperiment,
    event_type: ExperimentEventType,
) -> ExperimentEvent:
    events = replayed.events(event_type)
    if len(events) != 1:
        raise RetrospectiveEvaluationError(
            f"Retrospective evaluation requires exactly one effective {event_type.value} event."
        )
    return events[0]


def _validate_protocol_links(
    replayed: ReplayedExperiment,
    cohort: RetrospectiveCohortEvidence,
    proposal: ExperimentEvent,
    acceptance: ExperimentEvent,
    confirmation: ExperimentEvent,
) -> None:
    if not isinstance(proposal.payload, ExperimentProposedPayload):
        raise RetrospectiveEvaluationError("The effective retrospective proposal payload is invalid.")
    if not isinstance(acceptance.payload, ExperimentDecisionPayload):
        raise RetrospectiveEvaluationError("The effective retrospective acceptance payload is invalid.")
    if not isinstance(confirmation.payload, SettingChangeConfirmedPayload):
        raise RetrospectiveEvaluationError("The effective retrospective boundary payload is invalid.")
    if (
        acceptance.payload.proposal_event_id != proposal.record_id
        or confirmation.payload.accepted_event_id != acceptance.record_id
        or confirmation.payload.applied_change != proposal.payload.proposal.proposed_change
    ):
        raise RetrospectiveEvaluationError(
            "The effective retrospective proposal, acceptance, and boundary chain is inconsistent."
        )
    if any(
        event.experiment_record_id != replayed.experiment.record_id
        for event in (proposal, acceptance, confirmation)
    ):
        raise RetrospectiveEvaluationError(
            "The effective retrospective protocol must belong to the evaluated experiment."
        )
    if any(
        cohort.record_id not in event.source_record_ids
        for event in (proposal, acceptance, confirmation)
    ):
        raise RetrospectiveEvaluationError(
            "The effective retrospective protocol must link the selected cohort."
        )


def _effective_user_evidence(
    replayed: ReplayedExperiment,
    cohort: RetrospectiveCohortEvidence,
) -> tuple[
    tuple[RetrospectiveNightEvidence, ...],
    tuple[SleepJournalEntry, ...],
    tuple[ExperimentEvent, ...],
]:
    evidence = replayed.effective_retrospective_evidence
    expected_night_ids = tuple(night.record_id for night in cohort.nights)
    if tuple(value.night_record_id for value in evidence) != expected_night_ids:
        raise RetrospectiveEvaluationError(
            "Effective retrospective evidence must cover every selected cohort night in order."
        )
    if any(
        value.experiment_record_id != replayed.experiment.record_id
        or value.cohort_record_id != cohort.record_id
        or value.cohort_night_index != index
        for index, value in enumerate(evidence)
    ):
        raise RetrospectiveEvaluationError(
            "Effective retrospective evidence does not link the evaluated experiment and cohort exactly."
        )
    linked_event_ids = {
        identifier
        for value in evidence
        for identifier in (
            *((value.journal_event_id,) if value.journal_event_id is not None else ()),
            *value.confounder_event_ids,
            *value.adverse_effect_event_ids,
        )
    }
    evidence_events = tuple(
        event
        for event in replayed.effective_events
        if event.event_type in _USER_EVIDENCE_EVENT_TYPES
    )
    if {event.record_id for event in evidence_events} != linked_event_ids:
        raise RetrospectiveEvaluationError(
            "Every effective user-evidence event must resolve to exactly one retrospective night manifest."
        )
    expected_journals = {
        value.journal_entry.record_id: value.journal_entry
        for value in evidence
        if value.journal_entry is not None
    }
    actual_journals = {
        value.record_id: value for value in replayed.effective_journal_entries
    }
    if actual_journals != expected_journals:
        raise RetrospectiveEvaluationError(
            "Effective journal entries must exactly match the retrospective night manifests."
        )
    journals = tuple(
        value.journal_entry
        for value in evidence
        if value.journal_entry is not None
    )
    return evidence, journals, evidence_events


def _normalized_inventory(
    nights: tuple[NightRecord, ...],
) -> tuple[set[str], set[str]]:
    records: set[str] = set()
    provenance: set[str] = set()
    for night in nights:
        records.add(night.record_id)
        _add_provenance(night.provenance, records, provenance)
        for session in night.sessions:
            records.add(session.record_id)
            _add_provenance(session.provenance, records, provenance)
            for setting in session.settings:
                records.add(setting.record_id)
                _add_provenance(setting.provenance, records, provenance)
            for event in session.events:
                records.add(event.record_id)
                _add_provenance(event.provenance, records, provenance)
            for signal in session.signals:
                records.add(signal.record_id)
                _add_provenance(signal.provenance, records, provenance)
                for segment in signal.segments:
                    records.add(segment.record_id)
                    _add_provenance(segment.provenance, records, provenance)
    return records, provenance


def _add_provenance(
    value: ProvenanceRecord,
    records: set[str],
    provenance: set[str],
) -> None:
    provenance.add(value.record_id)
    provenance.update(value.parent_provenance_ids)
    records.update(
        f"{reference.source_record_type}:{reference.source_record_id}"
        for reference in value.source_references
    )


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RetrospectiveEvaluationError(f"The {label} must be nonempty text.")


def _text_tuple(
    values: object,
    label: str,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    if (
        type(values) is not tuple
        or any(type(value) is not str or not value.strip() for value in values)
        or (required and not values)
    ):
        raise RetrospectiveEvaluationError(
            f"The {label} must be an immutable{' nonempty' if required else ''} text tuple."
        )
    return values


def _typed_tuple(
    values: object,
    expected_type: type,
    label: str,
    *,
    required: bool = False,
) -> tuple:
    if (
        type(values) is not tuple
        or any(not isinstance(value, expected_type) for value in values)
        or (required and not values)
    ):
        raise RetrospectiveEvaluationError(
            f"The {label} must be an immutable{' nonempty' if required else ''} typed tuple."
        )
    return values


def _unique(values: tuple, label: str) -> None:
    if len(set(values)) != len(values):
        raise RetrospectiveEvaluationError(f"The {label} must be unique.")
