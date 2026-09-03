"""Deterministic, traceable retrospective evidence reporting."""

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import math
from typing import Final

from pap_pilot.engine.experiments import (
    OUTCOME_THRESHOLDS,
    PSMinRetrospectiveFixture,
    RetrospectiveFixtureEvaluationStatus,
    RetrospectiveMissingInputId,
    reconstruct_ps_min_experiment_fixture,
)
from pap_pilot.engine.experiments.allocation import ExperimentPeriod
from pap_pilot.engine.experiments.classification import OutcomeDirection, OutcomeId
from pap_pilot.engine.model import SourceClass


RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID: Final = "pap-pilot.retrospective-evidence-report"
RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION: Final = 1
RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION: Final = 1
RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION: Final = "0.1.0"
RETROSPECTIVE_EVIDENCE_REPORT_FORMAT: Final = "pap-pilot.retrospective-evidence-report-json"
RETROSPECTIVE_EVIDENCE_REPORT_FORMAT_VERSION: Final = 1

_OBJECTIVE_OUTCOMES: Final = (
    OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP,
    OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO,
)
_SUBJECTIVE_OUTCOMES: Final = (
    OutcomeId.AWAKENINGS_COUNT,
    OutcomeId.SLEEP_QUALITY,
    OutcomeId.MORNING_ENERGY,
    OutcomeId.DAYTIME_TIREDNESS,
)
_THRESHOLDS: Final = {threshold.outcome_id: threshold for threshold in OUTCOME_THRESHOLDS}


class RetrospectiveEvidenceReportError(ValueError):
    """Raised when a retrospective report or serialized value is invalid."""


class EvidenceAvailability(StrEnum):
    """Whether a report section contains attributable observations."""

    MISSING = "missing"
    NOT_ISSUED = "not_issued"


@dataclass(frozen=True, slots=True)
class ReportKnownChange:
    """The one retained setting change, without inferred timing."""

    setting_name: str
    baseline_value: float
    intervention_value: float
    unit: str
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (self.setting_name, self.baseline_value, self.intervention_value, self.unit) != ("ps_min", 2.0, 1.0, "cm H₂O"):
            raise RetrospectiveEvidenceReportError("Report version 1 is restricted to the retained PS Min 2-to-1 change.")
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "known-change source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportKnownFact:
    """One retained statement and its source links."""

    record_id: str
    statement: str
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.record_id, "known-fact identifier")
        _text(self.statement, "known-fact statement")
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "known-fact source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportHistoryEvent:
    """One replayed fixture event with enough linkage for review."""

    record_id: str
    sequence_number: int
    event_type: str
    source_class: SourceClass
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.record_id, "history-event identifier")
        if type(self.sequence_number) is not int or self.sequence_number < 1:
            raise RetrospectiveEvidenceReportError("A history event requires a positive sequence number.")
        _text(self.event_type, "history-event type")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise RetrospectiveEvidenceReportError("Retrospective report history must retain companion-derived source class.")
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "history-event source identifiers"))
        object.__setattr__(self, "source_provenance_ids", _identifiers(self.source_provenance_ids, "history-event provenance identifiers"))


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    """Baseline or intervention cohort inventory."""

    period: ExperimentPeriod
    availability: EvidenceAvailability
    night_count: int
    night_record_ids: tuple[str, ...]
    structural_quality_report_ids: tuple[str, ...]
    signal_quality_report_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod) or self.availability is not EvidenceAvailability.MISSING:
            raise RetrospectiveEvidenceReportError("The version-1 fixture report requires missing baseline and intervention periods.")
        if self.night_count != 0 or any((self.night_record_ids, self.structural_quality_report_ids, self.signal_quality_report_ids)):
            raise RetrospectiveEvidenceReportError("A missing period cannot claim retained night or quality-report evidence.")
        object.__setattr__(self, "reason_codes", _identifiers(self.reason_codes, "period reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "period source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportArmSummary:
    """Explicit empty per-period outcome summary."""

    period: ExperimentPeriod
    availability: EvidenceAvailability
    count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    median_absolute_deviation: float | None
    evidence_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod) or self.availability is not EvidenceAvailability.MISSING:
            raise RetrospectiveEvidenceReportError("An empty report arm must identify a supported missing period.")
        if self.count != 0 or any(value is not None for value in (self.minimum, self.median, self.maximum, self.median_absolute_deviation)) or self.evidence_record_ids:
            raise RetrospectiveEvidenceReportError("A missing report arm cannot contain a count, summary, or evidence identifier.")


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    """One objective metric or structured subjective outcome."""

    outcome_id: OutcomeId
    unit: str
    favorable_direction: OutcomeDirection
    prespecified_threshold: float
    availability: EvidenceAvailability
    baseline: ReportArmSummary
    intervention: ReportArmSummary
    intervention_minus_baseline: float | None
    outcome_state: str | None
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        threshold = _THRESHOLDS.get(self.outcome_id)
        if threshold is None or (self.unit, self.favorable_direction, self.prespecified_threshold) != (threshold.unit, threshold.favorable_direction, threshold.magnitude):
            raise RetrospectiveEvidenceReportError("A report outcome must retain its accepted version-1 threshold contract.")
        if self.availability is not EvidenceAvailability.MISSING or self.intervention_minus_baseline is not None or self.outcome_state is not None:
            raise RetrospectiveEvidenceReportError("An unavailable outcome cannot claim a change or outcome state.")
        if (self.baseline.period, self.intervention.period) != (ExperimentPeriod.BASELINE, ExperimentPeriod.INTERVENTION):
            raise RetrospectiveEvidenceReportError("A report outcome requires baseline and intervention arms in order.")
        object.__setattr__(self, "reason_codes", _identifiers(self.reason_codes, "outcome reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "outcome source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportEvidenceInventory:
    """Status and count for a required cross-cutting evidence family."""

    availability: EvidenceAvailability
    record_count: int
    record_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.availability is not EvidenceAvailability.MISSING or self.record_count != 0 or self.record_ids:
            raise RetrospectiveEvidenceReportError("A missing evidence inventory cannot claim retained records.")
        object.__setattr__(self, "reason_codes", _identifiers(self.reason_codes, "inventory reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "inventory source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportRepresentativeInterval:
    """A deliberately empty period interval slot for later evidence."""

    period: ExperimentPeriod
    availability: EvidenceAvailability
    interval_record_id: str | None
    start_ms: int | None
    end_ms: int | None
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod) or self.availability is not EvidenceAvailability.MISSING:
            raise RetrospectiveEvidenceReportError("A representative interval requires a supported missing period.")
        if any(value is not None for value in (self.interval_record_id, self.start_ms, self.end_ms)):
            raise RetrospectiveEvidenceReportError("A missing representative interval cannot contain an identifier or bounds.")
        object.__setattr__(self, "reason_codes", _identifiers(self.reason_codes, "interval reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "interval source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportMissingInput:
    """One absent fixture input retained in the report."""

    input_id: RetrospectiveMissingInputId
    description: str
    blocks: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.input_id, RetrospectiveMissingInputId):
            raise RetrospectiveEvidenceReportError("A report missing input requires a supported identifier.")
        _text(self.description, "missing-input description")
        object.__setattr__(self, "blocks", _identifiers(self.blocks, "blocked operations"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "missing-input source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportClassification:
    """Explicit absence of a deterministic outcome and action."""

    availability: EvidenceAvailability
    classification_record_id: str | None
    classification: str | None
    action: str | None
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.availability is not EvidenceAvailability.NOT_ISSUED or any(value is not None for value in (self.classification_record_id, self.classification, self.action)):
            raise RetrospectiveEvidenceReportError("An unissued classification cannot claim a result or action.")
        object.__setattr__(self, "reason_codes", _identifiers(self.reason_codes, "classification reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "classification source identifiers"))


@dataclass(frozen=True, slots=True)
class ReportProvenance:
    """Source and producer inventory for the report itself."""

    source_class: SourceClass
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    producer_id: str
    producer_version: str

    def __post_init__(self) -> None:
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise RetrospectiveEvidenceReportError("A retrospective evidence report must be companion-derived.")
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "report source identifiers"))
        object.__setattr__(self, "source_provenance_ids", _identifiers(self.source_provenance_ids, "report provenance identifiers"))
        _text(self.producer_id, "report producer identifier")
        _text(self.producer_version, "report producer version")


@dataclass(frozen=True, slots=True)
class RetrospectiveEvidenceReport:
    """Versioned structured report generated from the retained S31 fixture."""

    record_id: str
    fixture_record_id: str
    experiment_record_id: str
    title: str
    evaluation_record_id: str
    evaluation_status: RetrospectiveFixtureEvaluationStatus
    known_change: ReportKnownChange
    known_facts: tuple[ReportKnownFact, ...]
    history: tuple[ReportHistoryEvent, ...]
    periods: tuple[ReportPeriod, ...]
    objective_metrics: tuple[ReportOutcome, ...]
    subjective_outcomes: tuple[ReportOutcome, ...]
    quality_evidence: ReportEvidenceInventory
    confounder_evidence: ReportEvidenceInventory
    adverse_effect_evidence: ReportEvidenceInventory
    representative_intervals: tuple[ReportRepresentativeInterval, ...]
    missing_inputs: tuple[ReportMissingInput, ...]
    classification: ReportClassification
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance: ReportProvenance
    schema_id: str = RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID
    schema_version: int = RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION
    record_version: int = RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION
    engine_version: str = RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "report identifier")
        for value, label in ((self.fixture_record_id, "fixture identifier"), (self.experiment_record_id, "experiment identifier"), (self.title, "report title"), (self.evaluation_record_id, "evaluation identifier")):
            _text(value, label)
        if self.evaluation_status is not RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION:
            raise RetrospectiveEvidenceReportError("Report version 1 cannot claim the incomplete fixture is evaluable.")
        _typed_tuple(self.known_facts, ReportKnownFact, "known facts", required=True)
        history = _typed_tuple(self.history, ReportHistoryEvent, "history", required=True)
        periods = _typed_tuple(self.periods, ReportPeriod, "periods", required=True)
        objective = _typed_tuple(self.objective_metrics, ReportOutcome, "objective metrics", required=True)
        subjective = _typed_tuple(self.subjective_outcomes, ReportOutcome, "subjective outcomes", required=True)
        intervals = _typed_tuple(self.representative_intervals, ReportRepresentativeInterval, "representative intervals", required=True)
        missing = _typed_tuple(self.missing_inputs, ReportMissingInput, "missing inputs", required=True)
        if tuple(value.sequence_number for value in history) != tuple(range(1, len(history) + 1)):
            raise RetrospectiveEvidenceReportError("Report history must retain contiguous fixture sequence order.")
        if tuple(value.period for value in periods) != tuple(ExperimentPeriod) or tuple(value.period for value in intervals) != tuple(ExperimentPeriod):
            raise RetrospectiveEvidenceReportError("Report periods and representative intervals must cover baseline and intervention in canonical order.")
        if tuple(value.outcome_id for value in objective) != _OBJECTIVE_OUTCOMES or tuple(value.outcome_id for value in subjective) != _SUBJECTIVE_OUTCOMES:
            raise RetrospectiveEvidenceReportError("Report version 1 must contain exactly the accepted objective and subjective outcomes in canonical order.")
        if tuple(value.input_id for value in missing) != tuple(sorted(RetrospectiveMissingInputId, key=lambda value: value.value)):
            raise RetrospectiveEvidenceReportError("The report must contain every missing fixture input in canonical order.")
        if not all(isinstance(value, ReportEvidenceInventory) for value in (self.quality_evidence, self.confounder_evidence, self.adverse_effect_evidence)) or not isinstance(self.classification, ReportClassification) or not isinstance(self.provenance, ReportProvenance):
            raise RetrospectiveEvidenceReportError("The report requires immutable evidence, classification, and provenance sections.")
        uncertainty = _identifiers(self.uncertainty, "uncertainty statements")
        limitations = _identifiers(self.limitations, "limitation statements")
        inventory = set(self.provenance.source_record_ids)
        linked = {
            *(identifier for value in self.known_facts for identifier in value.source_record_ids),
            *(identifier for value in self.history for identifier in value.source_record_ids),
            *(identifier for value in self.periods for identifier in value.source_record_ids),
            *(identifier for value in (*self.objective_metrics, *self.subjective_outcomes) for identifier in value.source_record_ids),
            *(identifier for value in self.representative_intervals for identifier in value.source_record_ids),
            *(identifier for value in self.missing_inputs for identifier in value.source_record_ids),
            *self.known_change.source_record_ids,
            *self.quality_evidence.source_record_ids,
            *self.confounder_evidence.source_record_ids,
            *self.adverse_effect_evidence.source_record_ids,
            *self.classification.source_record_ids,
        }
        if not linked.issubset(inventory):
            raise RetrospectiveEvidenceReportError("The report provenance inventory must cover every section source link.")
        if (self.schema_id, self.schema_version, self.record_version, self.engine_version) != (RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID, RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION, RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION, RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION):
            raise RetrospectiveEvidenceReportError("The retrospective evidence report identity or version is unsupported.")
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "limitations", limitations)


def build_ps_min_retrospective_evidence_report(fixture: PSMinRetrospectiveFixture | None = None) -> RetrospectiveEvidenceReport:
    """Build the fixed S32 report without converting missing data into evidence."""

    source = reconstruct_ps_min_experiment_fixture() if fixture is None else fixture
    if not isinstance(source, PSMinRetrospectiveFixture):
        raise RetrospectiveEvidenceReportError("A report requires the immutable PS Min retrospective fixture.")
    missing_by_id = {value.input_id: value for value in source.missing_inputs}
    period_sources = _combined_sources(
        missing_by_id[RetrospectiveMissingInputId.APPLIED_CHANGE_BOUNDARY].source_record_ids,
        missing_by_id[RetrospectiveMissingInputId.BASELINE_INTERVENTION_NIGHTS].source_record_ids,
        missing_by_id[RetrospectiveMissingInputId.QUALITY_REPORTS].source_record_ids,
    )
    periods = tuple(
        ReportPeriod(
            period=period,
            availability=EvidenceAvailability.MISSING,
            night_count=0,
            night_record_ids=(),
            structural_quality_report_ids=(),
            signal_quality_report_ids=(),
            reason_codes=("applied_change_boundary_missing", "baseline_intervention_nights_missing", "quality_reports_missing"),
            source_record_ids=period_sources,
        )
        for period in ExperimentPeriod
    )
    objective_sources = missing_by_id[RetrospectiveMissingInputId.OBJECTIVE_METRIC_RESULTS].source_record_ids
    subjective_sources = missing_by_id[RetrospectiveMissingInputId.STRUCTURED_JOURNAL_REPORTS].source_record_ids
    objective = tuple(_missing_outcome(outcome_id, "objective_metric_results_missing", objective_sources) for outcome_id in _OBJECTIVE_OUTCOMES)
    subjective = tuple(_missing_outcome(outcome_id, "structured_journal_reports_missing", subjective_sources) for outcome_id in _SUBJECTIVE_OUTCOMES)
    interval_sources = missing_by_id[RetrospectiveMissingInputId.REPRESENTATIVE_INTERVALS].source_record_ids
    intervals = tuple(
        ReportRepresentativeInterval(
            period=period,
            availability=EvidenceAvailability.MISSING,
            interval_record_id=None,
            start_ms=None,
            end_ms=None,
            reason_codes=("representative_intervals_missing",),
            source_record_ids=interval_sources,
        )
        for period in ExperimentPeriod
    )
    quality_sources = missing_by_id[RetrospectiveMissingInputId.QUALITY_REPORTS].source_record_ids
    report_sources = _combined_sources(source.source_record_ids, (source.record_id, source.evaluation.record_id), tuple(value.record_id for value in source.known_facts), tuple(value.record_id for value in source.history))
    common_evidence = missing_by_id[RetrospectiveMissingInputId.CONFOUNDER_ADVERSE_EFFECT_EVIDENCE]
    known_change_fact = next(value for value in source.known_facts if value.record_id == "fact:ps-min-change")
    components = {
        "fixture_record_id": source.record_id,
        "experiment_record_id": source.experiment.record_id,
        "title": "Retrospective PS Min 2-to-1 evidence report",
        "evaluation_record_id": source.evaluation.record_id,
        "evaluation_status": source.evaluation.status,
        "known_change": ReportKnownChange(source.known_change.previous.name, source.known_change.previous.value, source.known_change.proposed.value, source.known_change.previous.unit, (known_change_fact.record_id, *known_change_fact.source_record_ids)),
        "known_facts": tuple(ReportKnownFact(value.record_id, value.statement, value.source_record_ids) for value in source.known_facts),
        "history": tuple(ReportHistoryEvent(value.record_id, value.sequence_number, value.event_type.value, value.source_class, value.source_record_ids, value.source_provenance_ids) for value in source.history),
        "periods": periods,
        "objective_metrics": objective,
        "subjective_outcomes": subjective,
        "quality_evidence": _missing_inventory("quality_reports_missing", quality_sources),
        "confounder_evidence": _missing_inventory("confounder_adverse_effect_evidence_missing", common_evidence.source_record_ids),
        "adverse_effect_evidence": _missing_inventory("confounder_adverse_effect_evidence_missing", common_evidence.source_record_ids),
        "representative_intervals": intervals,
        "missing_inputs": tuple(ReportMissingInput(value.input_id, value.description, value.blocks, value.source_record_ids) for value in source.missing_inputs),
        "classification": ReportClassification(EvidenceAvailability.NOT_ISSUED, None, None, None, source.evaluation.reason_codes, source.evaluation.source_record_ids),
        "uncertainty": (
            "The retained record does not establish the intended application boundary or identify baseline and intervention cohorts.",
            "Missing quality, metric, journal, confounder, adverse-effect, and waveform evidence prevents quantitative comparison.",
            "Absence of retained observations means unknown, not zero, unchanged, favorable, or safe.",
        ),
        "limitations": (*source.limitations, "This report is a structured evidence inventory; it contains no generated interpretation, clinical conclusion, or device-setting instruction."),
        "provenance": ReportProvenance(SourceClass.COMPANION_DERIVED, report_sources, source.experiment.source_provenance_ids, RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID, RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION),
    }
    identity = _canonical_json(
        _to_primitive(
            {
                "schema_id": RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID,
                "schema_version": RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
                "record_version": RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
                "engine_version": RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION,
                **components,
            }
        )
    )
    return RetrospectiveEvidenceReport(record_id=f"retrospective-evidence-report:{hashlib.sha256(identity.encode()).hexdigest()[:20]}", **components)


def serialize_retrospective_evidence_report(report: RetrospectiveEvidenceReport, *, pretty: bool = False) -> str:
    """Serialize one report to stable versioned JSON."""

    if not isinstance(report, RetrospectiveEvidenceReport):
        raise RetrospectiveEvidenceReportError("Only a retrospective evidence report can be serialized.")
    envelope = {
        "format": RETROSPECTIVE_EVIDENCE_REPORT_FORMAT,
        "format_version": RETROSPECTIVE_EVIDENCE_REPORT_FORMAT_VERSION,
        "report": _to_primitive(report),
    }
    try:
        if pretty:
            return json.dumps(envelope, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
        return _canonical_json(envelope)
    except (TypeError, ValueError) as error:
        raise RetrospectiveEvidenceReportError("The retrospective evidence report cannot be serialized safely.") from error


def _missing_outcome(outcome_id: OutcomeId, reason_code: str, source_record_ids: tuple[str, ...]) -> ReportOutcome:
    threshold = _THRESHOLDS[outcome_id]
    return ReportOutcome(
        outcome_id=outcome_id,
        unit=threshold.unit,
        favorable_direction=threshold.favorable_direction,
        prespecified_threshold=threshold.magnitude,
        availability=EvidenceAvailability.MISSING,
        baseline=_missing_arm(ExperimentPeriod.BASELINE),
        intervention=_missing_arm(ExperimentPeriod.INTERVENTION),
        intervention_minus_baseline=None,
        outcome_state=None,
        reason_codes=(reason_code,),
        source_record_ids=source_record_ids,
    )


def _missing_arm(period: ExperimentPeriod) -> ReportArmSummary:
    return ReportArmSummary(period, EvidenceAvailability.MISSING, 0, None, None, None, None, ())


def _missing_inventory(reason_code: str, source_record_ids: tuple[str, ...]) -> ReportEvidenceInventory:
    return ReportEvidenceInventory(EvidenceAvailability.MISSING, 0, (), (reason_code,), source_record_ids)


def _to_primitive(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_primitive(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise RetrospectiveEvidenceReportError(f"Unsupported report value type: {type(value).__name__}.")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _combined_sources(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({identifier for group in groups for identifier in group}))


def _typed_tuple(values: object, value_type: type, label: str, *, required: bool = False) -> tuple:
    if type(values) is not tuple or any(not isinstance(value, value_type) for value in values) or (required and not values):
        raise RetrospectiveEvidenceReportError(f"The {label} must be an immutable{' nonempty' if required else ''} {value_type.__name__} tuple.")
    return values


def _identifiers(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values or any(type(value) is not str or not value.strip() for value in values):
        raise RetrospectiveEvidenceReportError(f"The {label} must be an immutable nonempty text tuple.")
    if len(set(values)) != len(values):
        raise RetrospectiveEvidenceReportError(f"The {label} must contain unique values.")
    return tuple(sorted(values))


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RetrospectiveEvidenceReportError(f"The {label} must be nonempty text.")
