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
    RetrospectiveEvaluationBundle,
    RetrospectiveFixtureEvaluationStatus,
    RetrospectiveMissingInputId,
    reconstruct_ps_min_experiment_fixture,
)
from pap_pilot.engine.experiments.allocation import (
    ExperimentPeriod,
    NightAllocationStatus,
)
from pap_pilot.engine.experiments.classification import (
    OutcomeDirection,
    OutcomeEvidence,
    OutcomeId,
)
from pap_pilot.engine.experiments.journal import RetrospectiveEvidenceStatus
from pap_pilot.engine.experiments.model import (
    ExperimentEventType,
    ExperimentProposedPayload,
    SettingChangeConfirmedPayload,
)
from pap_pilot.engine.model import SignalRepresentation, SourceClass


RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID: Final = "pap-pilot.retrospective-evidence-report"
RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION: Final = 1
RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION: Final = 1
EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION: Final = 2
EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION: Final = 2
RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION: Final = "0.1.0"
RETROSPECTIVE_EVIDENCE_REPORT_FORMAT: Final = "pap-pilot.retrospective-evidence-report-json"
RETROSPECTIVE_EVIDENCE_REPORT_FORMAT_VERSION: Final = 1
RETROSPECTIVE_WAVEFORM_DISPLAY_CONTRACT_VERSION: Final = 1
MAX_RETROSPECTIVE_WAVEFORM_DURATION_MS: Final = 60_000
MAX_RETROSPECTIVE_WAVEFORM_SAMPLES: Final = 2_000

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
_SIGNAL_ORDER: Final = ("flow_rate", "mask_pressure", "leak_rate")
_SIGNAL_DISPLAY_KIND: Final = {
    "flow_rate": "flow_rate",
    "mask_pressure": "mask_pressure",
    "leak_rate": "leak",
}
_SIGNAL_UNITS: Final = {
    "flow_rate": "L/min",
    "mask_pressure": "cm H₂O",
    "leak_rate": "L/min",
}


class RetrospectiveEvidenceReportError(ValueError):
    """Raised when a retrospective report or serialized value is invalid."""


class EvidenceAvailability(StrEnum):
    """Whether a report section contains attributable observations."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"
    ISSUED = "issued"
    NOT_ISSUED = "not_issued"


class RetrospectiveEvidenceReportStatus(StrEnum):
    """Whether a report represents a completed deterministic evaluation."""

    EVALUATED = "evaluated"


@dataclass(frozen=True, slots=True)
class RetrospectiveRepresentativeIntervalSelection:
    """One caller-selected bounded raw-relative waveform interval."""

    record_id: str
    period: ExperimentPeriod
    night_record_id: str
    session_record_id: str
    start_ms: int | float
    end_ms: int | float
    signal_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.record_id, "representative selection identifier"),
            (self.night_record_id, "representative selection night identifier"),
            (self.session_record_id, "representative selection session identifier"),
        ):
            _text(value, label)
        if not isinstance(self.period, ExperimentPeriod):
            raise RetrospectiveEvidenceReportError("A representative selection requires a supported experiment period.")
        start = _timestamp(self.start_ms, "representative selection start")
        end = _timestamp(self.end_ms, "representative selection end")
        if start >= end or end - start > MAX_RETROSPECTIVE_WAVEFORM_DURATION_MS:
            raise RetrospectiveEvidenceReportError("A representative selection must be a positive half-open interval no longer than 60,000 ms.")
        signal_kinds = _optional_identifiers(self.signal_kinds, "representative selection signal kinds", required=True)
        if any(value not in _SIGNAL_ORDER for value in signal_kinds) or len(signal_kinds) > len(_SIGNAL_ORDER):
            raise RetrospectiveEvidenceReportError("A representative selection may contain only Flow Rate, Mask Pressure, and Leak.")
        object.__setattr__(self, "start_ms", start)
        object.__setattr__(self, "end_ms", end)
        object.__setattr__(self, "signal_kinds", tuple(value for value in _SIGNAL_ORDER if value in signal_kinds))


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
        if not isinstance(self.source_class, SourceClass):
            raise RetrospectiveEvidenceReportError("Retrospective report history must retain a supported source class.")
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
        if not isinstance(self.period, ExperimentPeriod) or self.availability not in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.MISSING}:
            raise RetrospectiveEvidenceReportError("A report period requires a supported period and availability state.")
        if type(self.night_count) is not int or self.night_count < 0 or self.night_count != len(self.night_record_ids):
            raise RetrospectiveEvidenceReportError("A report period count must match its retained night identifiers.")
        if self.availability is EvidenceAvailability.MISSING and (self.night_count != 0 or any((self.night_record_ids, self.structural_quality_report_ids, self.signal_quality_report_ids))):
            raise RetrospectiveEvidenceReportError("A missing period cannot claim retained night or quality-report evidence.")
        if self.availability is EvidenceAvailability.AVAILABLE and (not self.night_record_ids or not self.structural_quality_report_ids):
            raise RetrospectiveEvidenceReportError("An available period requires retained nights and structural quality evidence.")
        object.__setattr__(self, "night_record_ids", _optional_identifiers(self.night_record_ids, "period night identifiers"))
        object.__setattr__(self, "structural_quality_report_ids", _optional_identifiers(self.structural_quality_report_ids, "period structural-quality report identifiers"))
        object.__setattr__(self, "signal_quality_report_ids", _optional_identifiers(self.signal_quality_report_ids, "period signal-quality report identifiers"))
        object.__setattr__(self, "reason_codes", _optional_identifiers(self.reason_codes, "period reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "period source identifiers"))
        if not set((*self.night_record_ids, *self.structural_quality_report_ids, *self.signal_quality_report_ids)).issubset(self.source_record_ids):
            raise RetrospectiveEvidenceReportError("A report period must link every retained night and quality report.")


@dataclass(frozen=True, slots=True)
class ReportArmSummary:
    """One per-period outcome summary with explicit availability."""

    period: ExperimentPeriod
    availability: EvidenceAvailability
    count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    median_absolute_deviation: float | None
    evidence_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod) or self.availability not in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.MISSING}:
            raise RetrospectiveEvidenceReportError("A report arm requires a supported period and availability state.")
        if type(self.count) is not int or self.count < 0 or self.count != len(self.evidence_record_ids):
            raise RetrospectiveEvidenceReportError("A report arm count must match its evidence identifiers.")
        statistics = (self.minimum, self.median, self.maximum, self.median_absolute_deviation)
        if self.availability is EvidenceAvailability.MISSING and (self.count != 0 or any(value is not None for value in statistics)):
            raise RetrospectiveEvidenceReportError("A missing report arm cannot contain a count or summary.")
        if self.availability is EvidenceAvailability.AVAILABLE and (self.count == 0 or any(value is None for value in statistics)):
            raise RetrospectiveEvidenceReportError("An available report arm requires observations and every descriptive statistic.")
        for value in statistics:
            if value is not None:
                _number(value, "report arm statistic")
        object.__setattr__(self, "evidence_record_ids", _optional_identifiers(self.evidence_record_ids, "report arm evidence identifiers"))


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
        if self.availability not in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.PARTIAL, EvidenceAvailability.MISSING}:
            raise RetrospectiveEvidenceReportError("A report outcome has an unsupported availability state.")
        if (self.baseline.period, self.intervention.period) != (ExperimentPeriod.BASELINE, ExperimentPeriod.INTERVENTION):
            raise RetrospectiveEvidenceReportError("A report outcome requires baseline and intervention arms in order.")
        arm_availability = (self.baseline.availability, self.intervention.availability)
        expected_availability = EvidenceAvailability.AVAILABLE if arm_availability == (EvidenceAvailability.AVAILABLE, EvidenceAvailability.AVAILABLE) else EvidenceAvailability.PARTIAL if EvidenceAvailability.AVAILABLE in arm_availability else EvidenceAvailability.MISSING
        if self.availability is not expected_availability:
            raise RetrospectiveEvidenceReportError("A report outcome availability must match its retained arms.")
        if self.availability is EvidenceAvailability.AVAILABLE:
            _number(self.intervention_minus_baseline, "report outcome change")
            _text(self.outcome_state, "report outcome state")
        elif self.intervention_minus_baseline is not None:
            raise RetrospectiveEvidenceReportError("A partial or missing outcome cannot claim a complete change.")
        elif self.outcome_state is not None:
            _text(self.outcome_state, "report outcome state")
        object.__setattr__(self, "reason_codes", _optional_identifiers(self.reason_codes, "outcome reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "outcome source identifiers"))
        if not set((*self.baseline.evidence_record_ids, *self.intervention.evidence_record_ids)).issubset(self.source_record_ids):
            raise RetrospectiveEvidenceReportError("A report outcome must link every retained observation.")


@dataclass(frozen=True, slots=True)
class ReportEvidenceInventory:
    """Status and count for a required cross-cutting evidence family."""

    availability: EvidenceAvailability
    record_count: int
    record_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.availability not in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.PARTIAL, EvidenceAvailability.MISSING}:
            raise RetrospectiveEvidenceReportError("An evidence inventory has an unsupported availability state.")
        if type(self.record_count) is not int or self.record_count < 0 or self.record_count != len(self.record_ids):
            raise RetrospectiveEvidenceReportError("An evidence inventory count must match its record identifiers.")
        if self.availability is EvidenceAvailability.AVAILABLE and not self.record_ids:
            raise RetrospectiveEvidenceReportError("An available evidence inventory requires retained records.")
        if self.availability is EvidenceAvailability.MISSING and self.record_ids:
            raise RetrospectiveEvidenceReportError("A missing evidence inventory cannot claim attributable evidence records.")
        object.__setattr__(self, "record_ids", _optional_identifiers(self.record_ids, "inventory record identifiers"))
        object.__setattr__(self, "reason_codes", _optional_identifiers(self.reason_codes, "inventory reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "inventory source identifiers"))
        if not set(self.record_ids).issubset(self.source_record_ids):
            raise RetrospectiveEvidenceReportError("An evidence inventory must link every retained record.")


@dataclass(frozen=True, slots=True)
class ReportSignalExcerpt:
    """One exact bounded signal excerpt or an explicit missing state."""

    signal_kind: str
    availability: EvidenceAvailability
    signal_record_id: str | None
    unit: str
    representation: str | None
    sample_times_ms: tuple[float, ...]
    values: tuple[float, ...]
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.signal_kind not in _SIGNAL_DISPLAY_KIND.values() or self.availability not in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.MISSING}:
            raise RetrospectiveEvidenceReportError("A report signal excerpt has an unsupported kind or availability state.")
        expected_source_kind = next(key for key, value in _SIGNAL_DISPLAY_KIND.items() if value == self.signal_kind)
        if self.unit != _SIGNAL_UNITS[expected_source_kind]:
            raise RetrospectiveEvidenceReportError("A report signal excerpt must retain the normalized signal unit.")
        times = _number_tuple(self.sample_times_ms, "signal excerpt sample times")
        values = _number_tuple(self.values, "signal excerpt values")
        if self.availability is EvidenceAvailability.MISSING:
            if self.signal_record_id is not None or self.representation is not None or times or values:
                raise RetrospectiveEvidenceReportError("A missing signal excerpt cannot contain an identifier, representation, or samples.")
        else:
            _text(self.signal_record_id, "signal excerpt identifier")
            if self.representation not in {value.value for value in SignalRepresentation}:
                raise RetrospectiveEvidenceReportError("An available signal excerpt requires a supported representation.")
            if len(times) != len(values) or not 2 <= len(times) <= MAX_RETROSPECTIVE_WAVEFORM_SAMPLES or any(current >= following for current, following in zip(times, times[1:])):
                raise RetrospectiveEvidenceReportError("An available signal excerpt requires two to 2,000 strictly ordered paired samples.")
        object.__setattr__(self, "sample_times_ms", times)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "reason_codes", _optional_identifiers(self.reason_codes, "signal excerpt reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "signal excerpt source identifiers"))
        if self.signal_record_id is not None and self.signal_record_id not in self.source_record_ids:
            raise RetrospectiveEvidenceReportError("A signal excerpt must link its normalized signal record.")


@dataclass(frozen=True, slots=True)
class ReportRepresentativeInterval:
    """A missing or available representative interval."""

    period: ExperimentPeriod
    availability: EvidenceAvailability
    interval_record_id: str | None
    start_ms: int | None
    end_ms: int | None
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod) or self.availability not in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.MISSING}:
            raise RetrospectiveEvidenceReportError("A representative interval requires a supported period and availability state.")
        if self.availability is EvidenceAvailability.MISSING:
            if any(value is not None for value in (self.interval_record_id, self.start_ms, self.end_ms)):
                raise RetrospectiveEvidenceReportError("A missing representative interval cannot contain an identifier or bounds.")
        else:
            _text(self.interval_record_id, "representative interval identifier")
            start = _timestamp(self.start_ms, "representative interval start")
            end = _timestamp(self.end_ms, "representative interval end")
            if start >= end or end - start > MAX_RETROSPECTIVE_WAVEFORM_DURATION_MS:
                raise RetrospectiveEvidenceReportError("An available representative interval must be positive and bounded.")
            object.__setattr__(self, "start_ms", start)
            object.__setattr__(self, "end_ms", end)
        object.__setattr__(self, "reason_codes", _optional_identifiers(self.reason_codes, "interval reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "interval source identifiers"))
        if self.interval_record_id is not None and self.interval_record_id not in self.source_record_ids:
            raise RetrospectiveEvidenceReportError("A representative interval must link its selection record.")


@dataclass(frozen=True, slots=True)
class ReportWaveformInterval(ReportRepresentativeInterval):
    """An available representative interval carrying exact supplied-source samples."""

    display_contract_version: int = RETROSPECTIVE_WAVEFORM_DISPLAY_CONTRACT_VERSION
    signals: tuple[ReportSignalExcerpt, ...] = ()

    def __post_init__(self) -> None:
        super(ReportWaveformInterval, self).__post_init__()
        if self.availability is not EvidenceAvailability.AVAILABLE or self.display_contract_version != RETROSPECTIVE_WAVEFORM_DISPLAY_CONTRACT_VERSION:
            raise RetrospectiveEvidenceReportError("A waveform interval requires the available version-1 display contract.")
        signals = _typed_tuple(self.signals, ReportSignalExcerpt, "waveform signal excerpts", required=True)
        if len(signals) > len(_SIGNAL_ORDER) or len({value.signal_kind for value in signals}) != len(signals):
            raise RetrospectiveEvidenceReportError("A waveform interval requires one to three unique signal excerpts.")
        if not any(value.availability is EvidenceAvailability.AVAILABLE for value in signals):
            raise RetrospectiveEvidenceReportError("A waveform interval requires at least one attributable signal excerpt.")
        if any(time < self.start_ms or time >= self.end_ms for signal in signals for time in signal.sample_times_ms):
            raise RetrospectiveEvidenceReportError("Every signal sample must lie inside its representative interval.")
        object.__setattr__(self, "signals", signals)


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
    """An issued deterministic outcome/action or explicit absence."""

    availability: EvidenceAvailability
    classification_record_id: str | None
    classification: str | None
    action: str | None
    reason_codes: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.availability is EvidenceAvailability.NOT_ISSUED:
            if any(value is not None for value in (self.classification_record_id, self.classification, self.action)):
                raise RetrospectiveEvidenceReportError("An unissued classification cannot claim a result or action.")
        elif self.availability is EvidenceAvailability.ISSUED:
            for value, label in (
                (self.classification_record_id, "classification identifier"),
                (self.classification, "classification value"),
                (self.action, "classification action"),
            ):
                _text(value, label)
        else:
            raise RetrospectiveEvidenceReportError("A report classification has an unsupported availability state.")
        object.__setattr__(self, "reason_codes", _optional_identifiers(self.reason_codes, "classification reason codes"))
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "classification source identifiers"))
        if self.classification_record_id is not None and self.classification_record_id not in self.source_record_ids:
            raise RetrospectiveEvidenceReportError("An issued classification must link its deterministic record.")


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
    """Versioned structured retrospective evidence report."""

    record_id: str
    fixture_record_id: str
    experiment_record_id: str
    title: str
    evaluation_record_id: str
    evaluation_status: RetrospectiveFixtureEvaluationStatus | RetrospectiveEvidenceReportStatus
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
        missing_fixture_report = self.evaluation_status is RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION
        evaluated_report = self.evaluation_status is RetrospectiveEvidenceReportStatus.EVALUATED
        if not (missing_fixture_report or evaluated_report):
            raise RetrospectiveEvidenceReportError("The retrospective report has an unsupported evaluation status.")
        _typed_tuple(self.known_facts, ReportKnownFact, "known facts", required=True)
        history = _typed_tuple(self.history, ReportHistoryEvent, "history", required=True)
        periods = _typed_tuple(self.periods, ReportPeriod, "periods", required=True)
        objective = _typed_tuple(self.objective_metrics, ReportOutcome, "objective metrics", required=True)
        subjective = _typed_tuple(self.subjective_outcomes, ReportOutcome, "subjective outcomes", required=True)
        intervals = _typed_tuple(self.representative_intervals, ReportRepresentativeInterval, "representative intervals", required=True)
        missing = _typed_tuple(self.missing_inputs, ReportMissingInput, "missing inputs")
        history_sequences = tuple(value.sequence_number for value in history)
        if len(set(history_sequences)) != len(history_sequences) or history_sequences != tuple(sorted(history_sequences)):
            raise RetrospectiveEvidenceReportError("Report history must retain unique increasing effective sequence order.")
        if tuple(value.period for value in periods) != tuple(ExperimentPeriod) or tuple(value.period for value in intervals) != tuple(ExperimentPeriod):
            raise RetrospectiveEvidenceReportError("Report periods and representative intervals must cover baseline and intervention in canonical order.")
        if tuple(value.outcome_id for value in objective) != _OBJECTIVE_OUTCOMES or tuple(value.outcome_id for value in subjective) != _SUBJECTIVE_OUTCOMES:
            raise RetrospectiveEvidenceReportError("Report version 1 must contain exactly the accepted objective and subjective outcomes in canonical order.")
        if tuple(value.input_id for value in missing) != tuple(sorted((value.input_id for value in missing), key=lambda value: value.value)) or len({value.input_id for value in missing}) != len(missing):
            raise RetrospectiveEvidenceReportError("Report missing inputs must be unique and in canonical order.")
        if missing_fixture_report and tuple(value.input_id for value in missing) != tuple(sorted(RetrospectiveMissingInputId, key=lambda value: value.value)):
            raise RetrospectiveEvidenceReportError("The fixture report must contain every missing input in canonical order.")
        if not all(isinstance(value, ReportEvidenceInventory) for value in (self.quality_evidence, self.confounder_evidence, self.adverse_effect_evidence)) or not isinstance(self.classification, ReportClassification) or not isinstance(self.provenance, ReportProvenance):
            raise RetrospectiveEvidenceReportError("The report requires immutable evidence, classification, and provenance sections.")
        uncertainty = _identifiers(self.uncertainty, "uncertainty statements")
        limitations = _identifiers(self.limitations, "limitation statements")
        inventory = set(self.provenance.source_record_ids)
        linked = {
            *(value.record_id for value in self.known_facts),
            *(value.record_id for value in self.history),
            *(identifier for value in self.known_facts for identifier in value.source_record_ids),
            *(identifier for value in self.history for identifier in value.source_record_ids),
            *(identifier for value in self.periods for identifier in (*value.night_record_ids, *value.structural_quality_report_ids, *value.signal_quality_report_ids)),
            *(identifier for value in self.periods for identifier in value.source_record_ids),
            *(identifier for value in (*self.objective_metrics, *self.subjective_outcomes) for identifier in (*value.baseline.evidence_record_ids, *value.intervention.evidence_record_ids)),
            *(identifier for value in (*self.objective_metrics, *self.subjective_outcomes) for identifier in value.source_record_ids),
            *(value.interval_record_id for value in self.representative_intervals if value.interval_record_id is not None),
            *(identifier for value in self.representative_intervals for identifier in value.source_record_ids),
            *(identifier for value in self.missing_inputs for identifier in value.source_record_ids),
            *self.known_change.source_record_ids,
            *self.quality_evidence.record_ids,
            *self.quality_evidence.source_record_ids,
            *self.confounder_evidence.record_ids,
            *self.confounder_evidence.source_record_ids,
            *self.adverse_effect_evidence.record_ids,
            *self.adverse_effect_evidence.source_record_ids,
            *((self.classification.classification_record_id,) if self.classification.classification_record_id is not None else ()),
            *self.classification.source_record_ids,
        }
        if not linked.issubset(inventory):
            raise RetrospectiveEvidenceReportError("The report provenance inventory must cover every section source link.")
        expected_versions = (
            RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID,
            RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION if missing_fixture_report else EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
            RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION if missing_fixture_report else EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
            RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION,
        )
        if (self.schema_id, self.schema_version, self.record_version, self.engine_version) != expected_versions:
            raise RetrospectiveEvidenceReportError("The retrospective evidence report identity or version is unsupported.")
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "limitations", limitations)


@dataclass(frozen=True, slots=True)
class EvaluatedRetrospectiveEvidenceReport(RetrospectiveEvidenceReport):
    """Schema-version-2 report built from one complete S37D evaluation bundle."""

    cohort_record_id: str = ""
    schema_version: int = EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION
    record_version: int = EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION

    def __post_init__(self) -> None:
        super(EvaluatedRetrospectiveEvidenceReport, self).__post_init__()
        _text(self.cohort_record_id, "evaluated report cohort identifier")
        if self.evaluation_status is not RetrospectiveEvidenceReportStatus.EVALUATED:
            raise RetrospectiveEvidenceReportError("An evaluated retrospective report must retain evaluated status.")
        if self.classification.availability is not EvidenceAvailability.ISSUED:
            raise RetrospectiveEvidenceReportError("An evaluated retrospective report requires its deterministic classification and action.")
        intervals = _typed_tuple(self.representative_intervals, ReportWaveformInterval, "evaluated representative intervals", required=True)
        linked_signal_sources = {
            identifier
            for interval in intervals
            for signal in interval.signals
            for identifier in signal.source_record_ids
        }
        if not linked_signal_sources.issubset(self.provenance.source_record_ids):
            raise RetrospectiveEvidenceReportError("Evaluated report provenance must cover every waveform source link.")
        if self.cohort_record_id not in self.provenance.source_record_ids:
            raise RetrospectiveEvidenceReportError("Evaluated report provenance must retain its selected cohort.")


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


def build_evaluated_retrospective_evidence_report(
    evaluation: RetrospectiveEvaluationBundle,
    representative_intervals: tuple[RetrospectiveRepresentativeIntervalSelection, ...],
) -> EvaluatedRetrospectiveEvidenceReport:
    """Build schema-version-2 report content from exact S37D results and explicit excerpts."""

    if not isinstance(evaluation, RetrospectiveEvaluationBundle):
        raise RetrospectiveEvidenceReportError("An evaluated report requires one S37D retrospective evaluation bundle.")
    selections = _typed_tuple(
        representative_intervals,
        RetrospectiveRepresentativeIntervalSelection,
        "representative interval selections",
        required=True,
    )
    if tuple(value.period for value in selections) != tuple(ExperimentPeriod) or len({value.record_id for value in selections}) != len(selections):
        raise RetrospectiveEvidenceReportError("Evaluated report selections must cover baseline and intervention once in canonical order.")

    fixture = reconstruct_ps_min_experiment_fixture()
    proposal_event = _one_report_event(evaluation, ExperimentEventType.EXPERIMENT_PROPOSED)
    confirmation_event = _one_report_event(evaluation, ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED)
    if not isinstance(proposal_event.payload, ExperimentProposedPayload) or not isinstance(confirmation_event.payload, SettingChangeConfirmedPayload):
        raise RetrospectiveEvidenceReportError("The evaluated report requires the effective proposal and confirmed boundary payloads.")
    proposal = proposal_event.payload.proposal
    change = confirmation_event.payload.applied_change
    if proposal.proposed_change != change:
        raise RetrospectiveEvidenceReportError("The evaluated report proposal and confirmed setting change must agree.")

    periods = tuple(_evaluated_period(evaluation, period) for period in ExperimentPeriod)
    objective = tuple(_evaluated_outcome(evaluation, outcome_id) for outcome_id in _OBJECTIVE_OUTCOMES)
    subjective = tuple(_evaluated_outcome(evaluation, outcome_id) for outcome_id in _SUBJECTIVE_OUTCOMES)
    quality = _quality_inventory(evaluation)
    confounders = _user_evidence_inventory(evaluation, "confounder")
    adverse_effects = _user_evidence_inventory(evaluation, "adverse_effect")
    intervals = tuple(_waveform_interval(evaluation, selection) for selection in selections)
    missing_inputs = _evaluated_missing_inputs(
        fixture,
        periods,
        objective,
        subjective,
        confounders,
        adverse_effects,
        evaluation,
    )
    retained_facts = tuple(
        ReportKnownFact(value.record_id, value.statement, value.source_record_ids)
        for value in fixture.known_facts
        if value.record_id in {"fact:analysis-contract", "fact:ps-min-change"}
    )
    history = tuple(
        ReportHistoryEvent(
            value.record_id,
            value.sequence_number,
            value.event_type.value,
            value.source_class,
            value.source_record_ids,
            value.source_provenance_ids,
        )
        for value in evaluation.effective_events
    )
    report_sources = _combined_sources(
        evaluation.source_record_ids,
        fixture.source_record_ids,
        (fixture.record_id, evaluation.record_id, evaluation.cohort_record_id),
        tuple(value.record_id for value in selections),
        tuple(identifier for value in intervals for identifier in value.source_record_ids),
        tuple(identifier for value in intervals for signal in value.signals for identifier in signal.source_record_ids),
    )
    limitations = tuple(
        sorted(
            {
                *evaluation.classification.limitations,
                *(value for result in evaluation.metric_results for value in result.limitations),
                "Representative waveforms are caller-selected bounded excerpts and are not an automatic or exhaustive survey of either period.",
                "This structured report contains no AI-generated prose, clinical conclusion, causal claim, or device-setting instruction.",
            }
        )
    )
    uncertainty = tuple(
        sorted(
            {
                "The retrospective comparison is unblinded and nonrandomized; the deterministic classification does not establish causality.",
                "Missing or insufficient evidence remains explicit and is not converted to zero, unchanged, favorable, or safe.",
                *(f"Classification reason: {value}." for value in evaluation.classification.reason_codes),
            }
        )
    )
    components = {
        "fixture_record_id": fixture.record_id,
        "experiment_record_id": evaluation.experiment_record_id,
        "title": "Retrospective PS Min 2-to-1 evidence report",
        "evaluation_record_id": evaluation.record_id,
        "evaluation_status": RetrospectiveEvidenceReportStatus.EVALUATED,
        "known_change": ReportKnownChange(
            change.previous.name,
            change.previous.value,
            change.proposed.value,
            change.previous.unit,
            _combined_sources((proposal_event.record_id, confirmation_event.record_id), proposal_event.source_record_ids, confirmation_event.source_record_ids),
        ),
        "known_facts": retained_facts,
        "history": history,
        "periods": periods,
        "objective_metrics": objective,
        "subjective_outcomes": subjective,
        "quality_evidence": quality,
        "confounder_evidence": confounders,
        "adverse_effect_evidence": adverse_effects,
        "representative_intervals": intervals,
        "missing_inputs": missing_inputs,
        "classification": ReportClassification(
            EvidenceAvailability.ISSUED,
            evaluation.classification.record_id,
            evaluation.classification.classification.value,
            evaluation.classification.action.value,
            evaluation.classification.reason_codes,
            _combined_sources(
                (evaluation.record_id, evaluation.classification.record_id),
                evaluation.classification.source_record_ids,
            ),
        ),
        "uncertainty": uncertainty,
        "limitations": limitations,
        "provenance": ReportProvenance(
            SourceClass.COMPANION_DERIVED,
            report_sources,
            evaluation.source_provenance_ids,
            RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID,
            RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION,
        ),
    }
    identity = _canonical_json(
        _to_primitive(
            {
                "schema_id": RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_ID,
                "schema_version": EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_SCHEMA_VERSION,
                "record_version": EVALUATED_RETROSPECTIVE_EVIDENCE_REPORT_RECORD_VERSION,
                "engine_version": RETROSPECTIVE_EVIDENCE_REPORT_ENGINE_VERSION,
                "cohort_record_id": evaluation.cohort_record_id,
                **components,
            }
        )
    )
    return EvaluatedRetrospectiveEvidenceReport(
        record_id=f"retrospective-evidence-report:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        cohort_record_id=evaluation.cohort_record_id,
        **components,
    )


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


def _one_report_event(evaluation: RetrospectiveEvaluationBundle, event_type: ExperimentEventType):
    values = tuple(value for value in evaluation.effective_events if value.event_type is event_type)
    if len(values) != 1:
        raise RetrospectiveEvidenceReportError(f"An evaluated report requires exactly one effective {event_type.value} event.")
    return values[0]


def _evaluated_period(evaluation: RetrospectiveEvaluationBundle, period: ExperimentPeriod) -> ReportPeriod:
    included = evaluation.allocation.included(period)
    night_ids = tuple(value.night_record_id for value in included)
    structural_ids = tuple(
        report.record_id
        for report in evaluation.allocation_structural_quality_reports
        if report.night_record_id in night_ids
    )
    session_ids = {
        session.record_id
        for night in evaluation.selected_nights
        if night.record_id in night_ids
        for session in night.sessions
    }
    signal_ids = tuple(
        report.record_id
        for report in evaluation.signal_quality_reports
        if report.session_record_id in session_ids
    )
    sources = _combined_sources(
        (evaluation.record_id, evaluation.allocation.record_id),
        tuple(value.record_id for value in evaluation.allocation.nights if value.period is period),
        night_ids,
        structural_ids,
        signal_ids,
    )
    if not included:
        return ReportPeriod(
            period,
            EvidenceAvailability.MISSING,
            0,
            (),
            (),
            (),
            (f"no_included_{period.value}_nights",),
            sources,
        )
    return ReportPeriod(
        period,
        EvidenceAvailability.AVAILABLE,
        len(night_ids),
        night_ids,
        structural_ids,
        signal_ids,
        (),
        sources,
    )


def _evaluated_outcome(evaluation: RetrospectiveEvaluationBundle, outcome_id: OutcomeId) -> ReportOutcome:
    evidence = evaluation.classification.outcome(outcome_id)
    baseline = _evaluated_arm(evidence, ExperimentPeriod.BASELINE)
    intervention = _evaluated_arm(evidence, ExperimentPeriod.INTERVENTION)
    if baseline.availability is EvidenceAvailability.AVAILABLE and intervention.availability is EvidenceAvailability.AVAILABLE:
        availability = EvidenceAvailability.AVAILABLE
    elif EvidenceAvailability.AVAILABLE in (baseline.availability, intervention.availability):
        availability = EvidenceAvailability.PARTIAL
    else:
        availability = EvidenceAvailability.MISSING
    related_sources = {
        evaluation.record_id,
        evaluation.classification.record_id,
        *(value.evidence_record_id for value in (*evidence.baseline.values, *evidence.intervention.values)),
    }
    if outcome_id in _OBJECTIVE_OUTCOMES:
        related_sources.update(
            result.record_id
            for result in evaluation.metric_results
            if result.metric_id.value == outcome_id.value
        )
    else:
        related_sources.update(value.record_id for value in evaluation.effective_journal_entries)
        related_sources.update(value.record_id for value in evaluation.retrospective_night_evidence)
    reasons = evaluation.classification.reason_codes if evidence.state.value in {"insufficient_evidence", "unstable"} else ()
    if evidence.state.value in {"insufficient_evidence", "unstable"} and not reasons:
        reasons = (f"{outcome_id.value}_{evidence.state.value}",)
    return ReportOutcome(
        outcome_id=outcome_id,
        unit=evidence.threshold.unit,
        favorable_direction=evidence.threshold.favorable_direction,
        prespecified_threshold=evidence.threshold.magnitude,
        availability=availability,
        baseline=baseline,
        intervention=intervention,
        intervention_minus_baseline=evidence.delta if availability is EvidenceAvailability.AVAILABLE else None,
        outcome_state=evidence.state.value,
        reason_codes=reasons,
        source_record_ids=tuple(sorted(related_sources)),
    )


def _evaluated_arm(evidence: OutcomeEvidence, period: ExperimentPeriod) -> ReportArmSummary:
    source = evidence.baseline if period is ExperimentPeriod.BASELINE else evidence.intervention
    if source.count == 0:
        return ReportArmSummary(period, EvidenceAvailability.MISSING, 0, None, None, None, None, ())
    return ReportArmSummary(
        period,
        EvidenceAvailability.AVAILABLE,
        source.count,
        source.minimum,
        source.median,
        source.maximum,
        source.median_absolute_deviation,
        tuple(value.evidence_record_id for value in source.values),
    )


def _quality_inventory(evaluation: RetrospectiveEvaluationBundle) -> ReportEvidenceInventory:
    reports = (
        *evaluation.allocation_structural_quality_reports,
        *evaluation.metric_structural_quality_reports,
        *evaluation.signal_quality_reports,
    )
    record_ids = tuple(
        sorted(
            {
                *(value.record_id for value in reports),
                *(finding.record_id for value in reports for finding in value.findings),
            }
        )
    )
    return ReportEvidenceInventory(
        EvidenceAvailability.AVAILABLE,
        len(record_ids),
        record_ids,
        (),
        _combined_sources((evaluation.record_id,), record_ids),
    )


def _user_evidence_inventory(evaluation: RetrospectiveEvaluationBundle, domain: str) -> ReportEvidenceInventory:
    if domain not in {"confounder", "adverse_effect"}:
        raise RetrospectiveEvidenceReportError("A report user-evidence inventory requires a supported domain.")
    status_name = f"{domain}_status"
    event_name = f"{domain}_event_ids"
    statuses = tuple(getattr(value, status_name) for value in evaluation.retrospective_night_evidence)
    answered = {
        RetrospectiveEvidenceStatus.NONE_REPORTED,
        RetrospectiveEvidenceStatus.REPORTED,
    }
    answered_manifests = tuple(
        value.record_id
        for value in evaluation.retrospective_night_evidence
        if getattr(value, status_name) in answered
    )
    event_ids = tuple(
        identifier
        for value in evaluation.retrospective_night_evidence
        for identifier in getattr(value, event_name)
    )
    record_ids = tuple(sorted({*answered_manifests, *event_ids}))
    answered_count = sum(value in answered for value in statuses)
    if answered_count == len(statuses):
        availability = EvidenceAvailability.AVAILABLE
        reasons = ()
    elif answered_count:
        availability = EvidenceAvailability.PARTIAL
        reasons = (f"{domain}_evidence_incomplete",)
    else:
        availability = EvidenceAvailability.MISSING
        reasons = (f"{domain}_evidence_missing",)
    sources = _combined_sources(
        (evaluation.record_id, evaluation.classification.record_id),
        tuple(value.record_id for value in evaluation.retrospective_night_evidence),
        event_ids,
    )
    return ReportEvidenceInventory(
        availability,
        len(record_ids),
        record_ids,
        reasons,
        sources,
    )


def _waveform_interval(
    evaluation: RetrospectiveEvaluationBundle,
    selection: RetrospectiveRepresentativeIntervalSelection,
) -> ReportWaveformInterval:
    allocation = next(
        (value for value in evaluation.allocation.nights if value.night_record_id == selection.night_record_id),
        None,
    )
    if allocation is None or allocation.status is not NightAllocationStatus.INCLUDED or allocation.period is not selection.period:
        raise RetrospectiveEvidenceReportError("A representative selection must identify an included night in its declared period.")
    if not any(
        value.session_record_id == selection.session_record_id
        and value.start_time_ms <= selection.start_ms
        and selection.end_ms <= value.end_time_ms
        for value in allocation.eligible_intervals
    ):
        raise RetrospectiveEvidenceReportError("A representative selection must lie wholly inside one eligible allocation interval.")
    night = next(value for value in evaluation.selected_nights if value.record_id == selection.night_record_id)
    session = next((value for value in night.sessions if value.record_id == selection.session_record_id), None)
    if session is None:
        raise RetrospectiveEvidenceReportError("A representative selection session must belong to its selected night.")
    signals = tuple(_signal_excerpt(selection, session, signal_kind) for signal_kind in selection.signal_kinds)
    sources = _combined_sources(
        (selection.record_id, night.record_id, session.record_id, evaluation.allocation.record_id, allocation.record_id),
        tuple(identifier for signal in signals for identifier in signal.source_record_ids),
    )
    return ReportWaveformInterval(
        period=selection.period,
        availability=EvidenceAvailability.AVAILABLE,
        interval_record_id=selection.record_id,
        start_ms=selection.start_ms,
        end_ms=selection.end_ms,
        reason_codes=(),
        source_record_ids=sources,
        signals=signals,
    )


def _signal_excerpt(selection, session, signal_kind: str) -> ReportSignalExcerpt:
    display_kind = _SIGNAL_DISPLAY_KIND[signal_kind]
    unit = _SIGNAL_UNITS[signal_kind]
    base_sources = (selection.record_id, selection.night_record_id, selection.session_record_id)
    signal = next((value for value in session.signals if value.signal_kind == signal_kind), None)
    if signal is None:
        return ReportSignalExcerpt(display_kind, EvidenceAvailability.MISSING, None, unit, None, (), (), ("signal_record_missing",), base_sources)
    signal_sources = _combined_sources(base_sources, (signal.record_id,))
    if signal.unit != unit:
        raise RetrospectiveEvidenceReportError("A selected waveform signal has an unsupported unit.")
    segments = tuple(
        value
        for value in signal.segments
        if value.start_time_ms <= selection.start_ms and selection.end_ms <= value.end_time_ms
    )
    if len(segments) != 1:
        sources = _combined_sources(signal_sources, tuple(value.record_id for value in signal.segments))
        return ReportSignalExcerpt(display_kind, EvidenceAvailability.MISSING, None, unit, None, (), (), ("selection_not_covered_by_one_signal_segment",), sources)
    segment = segments[0]
    pairs = tuple(
        (time, value)
        for time, value in zip(segment.sample_times_ms, segment.values)
        if selection.start_ms <= time < selection.end_ms
    )
    sources = _combined_sources(signal_sources, (segment.record_id,))
    if not 2 <= len(pairs) <= MAX_RETROSPECTIVE_WAVEFORM_SAMPLES or any(current[0] >= following[0] for current, following in zip(pairs, pairs[1:])):
        return ReportSignalExcerpt(display_kind, EvidenceAvailability.MISSING, None, unit, None, (), (), ("bounded_signal_samples_unavailable",), sources)
    return ReportSignalExcerpt(
        display_kind,
        EvidenceAvailability.AVAILABLE,
        signal.record_id,
        unit,
        signal.representation.value,
        tuple(float(value[0]) for value in pairs),
        tuple(float(value[1]) for value in pairs),
        (),
        sources,
    )


def _evaluated_missing_inputs(
    fixture,
    periods,
    objective,
    subjective,
    confounders,
    adverse_effects,
    evaluation,
) -> tuple[ReportMissingInput, ...]:
    missing_ids = set()
    sources = {}
    if any(value.availability is EvidenceAvailability.MISSING for value in periods):
        missing_ids.add(RetrospectiveMissingInputId.BASELINE_INTERVENTION_NIGHTS)
        sources[RetrospectiveMissingInputId.BASELINE_INTERVENTION_NIGHTS] = tuple(identifier for value in periods for identifier in value.source_record_ids)
    if any(value.availability is not EvidenceAvailability.AVAILABLE for value in objective):
        missing_ids.add(RetrospectiveMissingInputId.OBJECTIVE_METRIC_RESULTS)
        sources[RetrospectiveMissingInputId.OBJECTIVE_METRIC_RESULTS] = tuple(identifier for value in objective for identifier in value.source_record_ids)
    if any(value.availability is not EvidenceAvailability.AVAILABLE for value in subjective):
        missing_ids.add(RetrospectiveMissingInputId.STRUCTURED_JOURNAL_REPORTS)
        sources[RetrospectiveMissingInputId.STRUCTURED_JOURNAL_REPORTS] = tuple(identifier for value in subjective for identifier in value.source_record_ids)
    if confounders.availability is not EvidenceAvailability.AVAILABLE or adverse_effects.availability is not EvidenceAvailability.AVAILABLE:
        missing_ids.add(RetrospectiveMissingInputId.CONFOUNDER_ADVERSE_EFFECT_EVIDENCE)
        sources[RetrospectiveMissingInputId.CONFOUNDER_ADVERSE_EFFECT_EVIDENCE] = (*confounders.source_record_ids, *adverse_effects.source_record_ids)
    templates = {value.input_id: value for value in fixture.missing_inputs}
    return tuple(
        ReportMissingInput(
            input_id,
            templates[input_id].description,
            templates[input_id].blocks,
            _combined_sources((evaluation.record_id,), tuple(sources[input_id])),
        )
        for input_id in sorted(missing_ids, key=lambda value: value.value)
    )


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
    return _optional_identifiers(values, label, required=True)


def _optional_identifiers(values: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if type(values) is not tuple or (required and not values) or any(type(value) is not str or not value.strip() for value in values):
        raise RetrospectiveEvidenceReportError(f"The {label} must be an immutable{' nonempty' if required else ''} text tuple.")
    if len(set(values)) != len(values):
        raise RetrospectiveEvidenceReportError(f"The {label} must contain unique values.")
    return tuple(sorted(values))


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise RetrospectiveEvidenceReportError(f"The {label} must be a finite number.")
    return float(value)


def _number_tuple(values: object, label: str) -> tuple[float, ...]:
    if type(values) is not tuple:
        raise RetrospectiveEvidenceReportError(f"The {label} must be an immutable numeric tuple.")
    return tuple(_number(value, label) for value in values)


def _timestamp(value: object, label: str) -> int | float:
    _number(value, label)
    return value


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RetrospectiveEvidenceReportError(f"The {label} must be nonempty text.")
