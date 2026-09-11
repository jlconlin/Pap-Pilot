"""Generic, source-independent experiment definition and comparison contracts."""

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from statistics import median
from typing import Final, TypeAlias

from pap_pilot.engine.experiments.model import ExperimentEvidenceInterval, ExperimentProposal
from pap_pilot.engine.experiments.safety import (
    PROSPECTIVE_SAFETY_POLICY_ID,
    PROSPECTIVE_SAFETY_POLICY_VERSION,
    ProspectiveSafetyEvidence,
    evaluate_prospective_safety,
)
from pap_pilot.engine.model import SourceClass


GENERIC_EXPERIMENT_SCHEMA_ID: Final = "pap-pilot.generic-experiment"
GENERIC_EXPERIMENT_SCHEMA_VERSION: Final = 1
GENERIC_EXPERIMENT_RECORD_VERSION: Final = 1
GENERIC_EXPERIMENT_ANALYSIS_ENGINE_VERSION: Final = "pap-pilot.generic-experiment-analysis-v1"
GENERIC_EXPERIMENT_SAFETY_DISPATCH_VERSION: Final = "pap-pilot.experiment-safety-dispatch-v1"

ExperimentValue: TypeAlias = bool | int | float | str


class GenericExperimentError(ValueError):
    """Raised when a generic experiment contract is invalid or inconsistent."""


class GenericExperimentMode(StrEnum):
    """Whether an experiment observes existing evidence or proposes future action."""

    RETROSPECTIVE = "retrospective"
    PROSPECTIVE = "prospective"


class GenericExperimentVariableKind(StrEnum):
    """Broad kind of the one variable deliberately compared by an experiment."""

    DEVICE_SETTING = "device_setting"
    EQUIPMENT = "equipment"
    BEHAVIOR = "behavior"
    ENVIRONMENT = "environment"
    OTHER = "other"


class GenericExperimentPeriodRole(StrEnum):
    """Analytical role of a named comparison period."""

    REFERENCE = "reference"
    COMPARISON = "comparison"


class GenericExperimentMetricStatus(StrEnum):
    """Whether one explicitly supplied nightly metric observation was calculated."""

    CALCULATED = "calculated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class GenericExperimentAnalysisStatus(StrEnum):
    """Completeness of descriptive comparisons across selected metrics and periods."""

    ANALYZED = "analyzed"
    PARTIAL = "partial"
    NOT_EVALUABLE = "not_evaluable"


class GenericExperimentSafetyStatus(StrEnum):
    """Outcome of routing a definition to its declared prospective safety policy."""

    NOT_APPLICABLE = "not_applicable"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    POLICY_UNAVAILABLE = "policy_unavailable"


@dataclass(frozen=True, slots=True)
class GenericExperimentChange:
    """One controlled variable change without assuming that it is a PAP setting."""

    variable_id: str
    label: str
    kind: GenericExperimentVariableKind
    reference_value: ExperimentValue
    comparison_value: ExperimentValue
    unit: str | None = None

    def __post_init__(self) -> None:
        _text(self.variable_id, "experiment variable identifier")
        _text(self.label, "experiment variable label")
        _enum(self.kind, GenericExperimentVariableKind, "experiment variable kind")
        _value(self.reference_value, "reference variable value")
        _value(self.comparison_value, "comparison variable value")
        _optional_text(self.unit, "experiment variable unit")
        if self.reference_value == self.comparison_value:
            raise GenericExperimentError("A generic experiment change requires distinct reference and comparison values.")


@dataclass(frozen=True, slots=True)
class GenericExperimentPeriod:
    """One explicitly named set of nights in a generic comparison."""

    period_id: str
    label: str
    role: GenericExperimentPeriodRole
    position: int
    night_record_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.period_id, "experiment period identifier")
        _text(self.label, "experiment period label")
        _enum(self.role, GenericExperimentPeriodRole, "experiment period role")
        if type(self.position) is not int or self.position < 0:
            raise GenericExperimentError("An experiment period position must be a nonnegative integer.")
        nights = _identifiers(self.night_record_ids, "experiment period night identifiers", required=True)
        sources = _identifiers(self.source_record_ids, "experiment period source identifiers", required=True)
        if not set(nights).issubset(sources):
            raise GenericExperimentError("Experiment period sources must include every assigned night.")
        object.__setattr__(self, "night_record_ids", nights)
        object.__setattr__(self, "source_record_ids", sources)


@dataclass(frozen=True, slots=True)
class GenericExperimentMetricSelection:
    """One metric selected before comparison, with no embedded outcome judgment."""

    metric_id: str
    label: str
    unit: str | None
    minimum_calculated_nights_per_period: int
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.metric_id, "selected metric identifier")
        _text(self.label, "selected metric label")
        _optional_text(self.unit, "selected metric unit")
        if type(self.minimum_calculated_nights_per_period) is not int or self.minimum_calculated_nights_per_period <= 0:
            raise GenericExperimentError("A selected metric requires a positive per-period evidence minimum.")
        object.__setattr__(self, "source_record_ids", _identifiers(self.source_record_ids, "selected metric source identifiers", required=True))


@dataclass(frozen=True, slots=True)
class GenericExperimentSafetyPolicy:
    """Versioned policy identity used only for prospective safety dispatch."""

    policy_id: str
    policy_version: int

    def __post_init__(self) -> None:
        _text(self.policy_id, "experiment safety-policy identifier")
        if type(self.policy_version) is not int or self.policy_version <= 0:
            raise GenericExperimentError("An experiment safety-policy version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class GenericExperimentDefinition:
    """Versioned experiment definition independent of any particular PAP variable."""

    record_id: str
    experiment_record_id: str
    title: str
    mode: GenericExperimentMode
    problem: str
    hypothesis: str
    competing_explanations: tuple[str, ...]
    change: GenericExperimentChange
    periods: tuple[GenericExperimentPeriod, ...]
    metric_selections: tuple[GenericExperimentMetricSelection, ...]
    evidence_record_ids: tuple[str, ...]
    representative_intervals: tuple[ExperimentEvidenceInterval, ...]
    expected_objective_effects: tuple[str, ...]
    expected_subjective_effects: tuple[str, ...]
    safety_policy: GenericExperimentSafetyPolicy | None
    invalid_night_criteria: tuple[str, ...]
    possible_adverse_effects: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    revert_conditions: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    schema_id: str = GENERIC_EXPERIMENT_SCHEMA_ID
    schema_version: int = GENERIC_EXPERIMENT_SCHEMA_VERSION
    record_version: int = GENERIC_EXPERIMENT_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "generic experiment-definition identifier")
        _text(self.experiment_record_id, "experiment record identifier")
        _text(self.title, "generic experiment title")
        _enum(self.mode, GenericExperimentMode, "generic experiment mode")
        _text(self.problem, "generic experiment problem")
        _text(self.hypothesis, "generic experiment hypothesis")
        _instance(self.change, GenericExperimentChange, "generic experiment change")
        alternatives = _texts(self.competing_explanations, "generic experiment competing explanations", required=True)
        periods = _typed_tuple(self.periods, GenericExperimentPeriod, "generic experiment periods", required=True)
        metrics = _typed_tuple(self.metric_selections, GenericExperimentMetricSelection, "generic experiment metric selections", required=True)
        if len(periods) < 2 or sum(period.role is GenericExperimentPeriodRole.REFERENCE for period in periods) != 1 or not any(period.role is GenericExperimentPeriodRole.COMPARISON for period in periods):
            raise GenericExperimentError("A generic experiment requires one reference period and at least one comparison period.")
        _unique(tuple(period.period_id for period in periods), "generic experiment period identifiers")
        _unique(tuple(period.position for period in periods), "generic experiment period positions")
        all_nights = tuple(night_id for period in periods for night_id in period.night_record_ids)
        _unique(all_nights, "generic experiment assigned night identifiers")
        _unique(tuple(metric.metric_id for metric in metrics), "generic experiment selected metric identifiers")
        evidence_ids = _identifiers(self.evidence_record_ids, "generic experiment evidence identifiers", required=True)
        intervals = _typed_tuple(self.representative_intervals, ExperimentEvidenceInterval, "generic experiment representative intervals", required=True)
        for interval in intervals:
            if interval.night_record_id not in all_nights or any(identifier not in evidence_ids for identifier in interval.source_record_ids):
                raise GenericExperimentError("A representative interval must belong to an assigned night and use declared experiment evidence.")
        if self.mode is GenericExperimentMode.PROSPECTIVE:
            _instance(self.safety_policy, GenericExperimentSafetyPolicy, "prospective experiment safety policy")
        elif self.safety_policy is not None:
            raise GenericExperimentError("A retrospective definition cannot imply that a prospective safety policy approved an action.")
        for field_name, label in (
            ("invalid_night_criteria", "generic experiment invalid-night criteria"),
            ("expected_objective_effects", "generic experiment expected objective effects"),
            ("expected_subjective_effects", "generic experiment expected subjective effects"),
            ("possible_adverse_effects", "generic experiment possible adverse effects"),
            ("stop_conditions", "generic experiment stop conditions"),
            ("revert_conditions", "generic experiment revert conditions"),
            ("limitations", "generic experiment limitations"),
        ):
            object.__setattr__(self, field_name, _texts(getattr(self, field_name), label, required=True))
        sources = _identifiers(self.source_record_ids, "generic experiment source identifiers", required=True)
        provenance = _identifiers(self.source_provenance_ids, "generic experiment source provenance identifiers", required=True)
        nested_sources = {self.experiment_record_id, *evidence_ids, *(identifier for period in periods for identifier in period.source_record_ids), *(identifier for metric in metrics for identifier in metric.source_record_ids)}
        if not nested_sources.issubset(sources):
            raise GenericExperimentError("Generic experiment sources must cover its experiment, periods, and metric definitions.")
        if self.source_class not in {SourceClass.COMPANION_DERIVED, SourceClass.USER_REPORTED}:
            raise GenericExperimentError("Generic experiment definitions must be companion-derived or user-reported.")
        if (self.schema_id, self.schema_version, self.record_version) != (GENERIC_EXPERIMENT_SCHEMA_ID, GENERIC_EXPERIMENT_SCHEMA_VERSION, GENERIC_EXPERIMENT_RECORD_VERSION):
            raise GenericExperimentError("The generic experiment schema identity or version is unsupported.")
        object.__setattr__(self, "competing_explanations", alternatives)
        object.__setattr__(self, "periods", tuple(sorted(periods, key=lambda period: (period.position, period.period_id))))
        object.__setattr__(self, "metric_selections", tuple(sorted(metrics, key=lambda metric: metric.metric_id)))
        object.__setattr__(self, "evidence_record_ids", evidence_ids)
        object.__setattr__(self, "representative_intervals", tuple(sorted(intervals, key=lambda interval: (interval.start_time_ms, interval.session_record_id))))
        object.__setattr__(self, "source_record_ids", sources)
        object.__setattr__(self, "source_provenance_ids", provenance)


@dataclass(frozen=True, slots=True)
class GenericExperimentMetricObservation:
    """One already-calculated or explicitly unavailable metric value for one night."""

    record_id: str
    metric_id: str
    night_record_id: str
    status: GenericExperimentMetricStatus
    value: float | None
    unit: str | None
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.record_id, "generic metric-observation identifier")
        _text(self.metric_id, "generic metric-observation metric identifier")
        _text(self.night_record_id, "generic metric-observation night identifier")
        _enum(self.status, GenericExperimentMetricStatus, "generic metric-observation status")
        _optional_text(self.unit, "generic metric-observation unit")
        sources = _identifiers(self.source_record_ids, "generic metric-observation source identifiers", required=True)
        provenance = _identifiers(self.source_provenance_ids, "generic metric-observation provenance identifiers", required=True)
        reasons = _identifiers(self.reason_codes, "generic metric-observation reason codes")
        if self.night_record_id not in sources:
            raise GenericExperimentError("A generic metric observation must retain its night as source evidence.")
        if self.status is GenericExperimentMetricStatus.CALCULATED:
            _number(self.value, "calculated generic metric-observation value")
            if reasons:
                raise GenericExperimentError("A calculated generic metric observation cannot carry failure reasons.")
        elif self.value is not None or not reasons:
            raise GenericExperimentError("An insufficient generic metric observation requires no value and at least one reason code.")
        object.__setattr__(self, "value", None if self.value is None else float(self.value))
        object.__setattr__(self, "source_record_ids", sources)
        object.__setattr__(self, "source_provenance_ids", provenance)
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class GenericExperimentPeriodSummary:
    """Descriptive values for one selected metric in one named period."""

    metric_id: str
    period_id: str
    status: GenericExperimentMetricStatus
    calculated_count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    observation_record_ids: tuple[str, ...]
    insufficient_observation_record_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.metric_id, "period-summary metric identifier")
        _text(self.period_id, "period-summary period identifier")
        _enum(self.status, GenericExperimentMetricStatus, "period-summary status")
        if type(self.calculated_count) is not int or self.calculated_count < 0:
            raise GenericExperimentError("A period-summary calculated count must be a nonnegative integer.")
        calculated_ids = _identifiers(self.observation_record_ids, "period-summary calculated observation identifiers")
        insufficient_ids = _identifiers(self.insufficient_observation_record_ids, "period-summary insufficient observation identifiers")
        if set(calculated_ids) & set(insufficient_ids) or self.calculated_count != len(calculated_ids):
            raise GenericExperimentError("Period-summary observation inventories must be disjoint and agree with the calculated count.")
        reasons = _identifiers(self.reason_codes, "period-summary reason codes")
        if self.status is GenericExperimentMetricStatus.CALCULATED:
            for value, label in ((self.minimum, "period-summary minimum"), (self.median, "period-summary median"), (self.maximum, "period-summary maximum")):
                _number(value, label)
            assert self.minimum is not None and self.median is not None and self.maximum is not None
            if not self.minimum <= self.median <= self.maximum or not calculated_ids or reasons:
                raise GenericExperimentError("A calculated period summary requires ordered values, observations, and no failure reasons.")
        elif any(value is not None for value in (self.minimum, self.median, self.maximum)) or not reasons:
            raise GenericExperimentError("An insufficient period summary requires no aggregate values and at least one reason.")
        object.__setattr__(self, "observation_record_ids", calculated_ids)
        object.__setattr__(self, "insufficient_observation_record_ids", insufficient_ids)
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class GenericExperimentComparison:
    """Descriptive median difference from a reference period to one comparison period."""

    metric_id: str
    reference_period_id: str
    comparison_period_id: str
    status: GenericExperimentMetricStatus
    reference_median: float | None
    comparison_median: float | None
    comparison_minus_reference: float | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.metric_id, "comparison metric identifier")
        _text(self.reference_period_id, "comparison reference-period identifier")
        _text(self.comparison_period_id, "comparison period identifier")
        if self.reference_period_id == self.comparison_period_id:
            raise GenericExperimentError("A comparison requires distinct reference and comparison periods.")
        _enum(self.status, GenericExperimentMetricStatus, "comparison status")
        reasons = _identifiers(self.reason_codes, "comparison reason codes")
        if self.status is GenericExperimentMetricStatus.CALCULATED:
            for value, label in ((self.reference_median, "comparison reference median"), (self.comparison_median, "comparison median"), (self.comparison_minus_reference, "comparison difference")):
                _number(value, label)
            assert self.reference_median is not None and self.comparison_median is not None and self.comparison_minus_reference is not None
            if not math.isclose(self.comparison_median - self.reference_median, self.comparison_minus_reference, rel_tol=0.0, abs_tol=1e-12) or reasons:
                raise GenericExperimentError("A calculated comparison must retain its exact descriptive difference without failure reasons.")
        elif any(value is not None for value in (self.reference_median, self.comparison_median, self.comparison_minus_reference)) or not reasons:
            raise GenericExperimentError("An insufficient comparison requires no values and at least one reason.")
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class GenericExperimentAnalysis:
    """Deterministic descriptive result with no clinical classification or next action."""

    record_id: str
    experiment_definition_id: str
    experiment_record_id: str
    status: GenericExperimentAnalysisStatus
    period_summaries: tuple[GenericExperimentPeriodSummary, ...]
    comparisons: tuple[GenericExperimentComparison, ...]
    metric_observation_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    schema_id: str = GENERIC_EXPERIMENT_SCHEMA_ID
    schema_version: int = GENERIC_EXPERIMENT_SCHEMA_VERSION
    record_version: int = GENERIC_EXPERIMENT_RECORD_VERSION
    engine_version: str = GENERIC_EXPERIMENT_ANALYSIS_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "generic experiment-analysis identifier")
        _text(self.experiment_definition_id, "generic experiment definition identifier")
        _text(self.experiment_record_id, "generic experiment record identifier")
        _enum(self.status, GenericExperimentAnalysisStatus, "generic experiment-analysis status")
        summaries = _typed_tuple(self.period_summaries, GenericExperimentPeriodSummary, "generic experiment period summaries", required=True)
        comparisons = _typed_tuple(self.comparisons, GenericExperimentComparison, "generic experiment comparisons", required=True)
        _unique(tuple((value.metric_id, value.period_id) for value in summaries), "generic experiment period-summary keys")
        _unique(tuple((value.metric_id, value.reference_period_id, value.comparison_period_id) for value in comparisons), "generic experiment comparison keys")
        object.__setattr__(self, "metric_observation_ids", _identifiers(self.metric_observation_ids, "generic experiment metric-observation identifiers", required=True))
        sources = _identifiers(self.source_record_ids, "generic experiment-analysis source identifiers", required=True)
        if self.experiment_definition_id not in sources or not set(self.metric_observation_ids).issubset(sources):
            raise GenericExperimentError("Generic experiment-analysis sources must include its definition and observations.")
        object.__setattr__(self, "source_record_ids", sources)
        object.__setattr__(self, "source_provenance_ids", _identifiers(self.source_provenance_ids, "generic experiment-analysis provenance identifiers", required=True))
        reasons = _identifiers(self.reason_codes, "generic experiment-analysis reason codes")
        if self.status is GenericExperimentAnalysisStatus.ANALYZED and reasons:
            raise GenericExperimentError("A complete generic experiment analysis cannot carry insufficiency reasons.")
        if self.status is not GenericExperimentAnalysisStatus.ANALYZED and not reasons:
            raise GenericExperimentError("An incomplete generic experiment analysis requires reason codes.")
        calculated_comparisons = sum(value.status is GenericExperimentMetricStatus.CALCULATED for value in comparisons)
        expected_status = GenericExperimentAnalysisStatus.ANALYZED if calculated_comparisons == len(comparisons) else GenericExperimentAnalysisStatus.PARTIAL if calculated_comparisons else GenericExperimentAnalysisStatus.NOT_EVALUABLE
        if self.status is not expected_status:
            raise GenericExperimentError("Generic experiment-analysis status must reflect its comparisons.")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "limitations", _texts(self.limitations, "generic experiment-analysis limitations", required=True))
        if self.source_class is not SourceClass.COMPANION_DERIVED or (self.schema_id, self.schema_version, self.record_version, self.engine_version) != (GENERIC_EXPERIMENT_SCHEMA_ID, GENERIC_EXPERIMENT_SCHEMA_VERSION, GENERIC_EXPERIMENT_RECORD_VERSION, GENERIC_EXPERIMENT_ANALYSIS_ENGINE_VERSION):
            raise GenericExperimentError("The generic experiment-analysis identity or provenance is unsupported.")
        object.__setattr__(self, "period_summaries", summaries)
        object.__setattr__(self, "comparisons", comparisons)


@dataclass(frozen=True, slots=True)
class PsMinSafetyPolicyInput:
    """Typed input for the one currently registered prospective policy."""

    proposal: ExperimentProposal
    evidence: ProspectiveSafetyEvidence

    def __post_init__(self) -> None:
        _instance(self.proposal, ExperimentProposal, "PS Min safety proposal")
        _instance(self.evidence, ProspectiveSafetyEvidence, "PS Min safety evidence")


@dataclass(frozen=True, slots=True)
class GenericExperimentSafetyResult:
    """Fail-closed result from generic policy dispatch."""

    experiment_definition_id: str
    status: GenericExperimentSafetyStatus
    policy_id: str | None
    policy_version: int | None
    failure_codes: tuple[str, ...]
    delegated_engine_version: str | None
    dispatch_version: str = GENERIC_EXPERIMENT_SAFETY_DISPATCH_VERSION

    def __post_init__(self) -> None:
        _text(self.experiment_definition_id, "safety-result experiment definition identifier")
        _enum(self.status, GenericExperimentSafetyStatus, "generic experiment safety status")
        _optional_text(self.policy_id, "safety-result policy identifier")
        if (self.policy_id is None) != (self.policy_version is None):
            raise GenericExperimentError("A safety result must retain both policy identity and version or neither.")
        if self.policy_version is not None and (type(self.policy_version) is not int or self.policy_version <= 0):
            raise GenericExperimentError("A safety-result policy version must be a positive integer.")
        failures = _identifiers(self.failure_codes, "generic experiment safety failure codes")
        if self.status is GenericExperimentSafetyStatus.ELIGIBLE and failures:
            raise GenericExperimentError("An eligible safety result cannot carry failure codes.")
        if self.status is not GenericExperimentSafetyStatus.ELIGIBLE and not failures:
            raise GenericExperimentError("A non-eligible safety result requires an explicit reason.")
        if self.status is GenericExperimentSafetyStatus.NOT_APPLICABLE and self.policy_id is not None:
            raise GenericExperimentError("A not-applicable safety result cannot imply that a policy was evaluated.")
        _optional_text(self.delegated_engine_version, "delegated safety engine version")
        if self.dispatch_version != GENERIC_EXPERIMENT_SAFETY_DISPATCH_VERSION:
            raise GenericExperimentError("The generic experiment safety-dispatch version is unsupported.")
        object.__setattr__(self, "failure_codes", failures)


def analyze_generic_experiment(definition: GenericExperimentDefinition, observations: tuple[GenericExperimentMetricObservation, ...]) -> GenericExperimentAnalysis:
    """Summarize explicitly assigned nightly metrics without assigning meaning or action."""

    _instance(definition, GenericExperimentDefinition, "generic experiment definition")
    values = _typed_tuple(observations, GenericExperimentMetricObservation, "generic experiment metric observations", required=True)
    _unique(tuple(value.record_id for value in values), "generic metric-observation record identifiers")
    _unique(tuple((value.metric_id, value.night_record_id) for value in values), "generic metric-observation metric/night pairs")
    metrics = {selection.metric_id: selection for selection in definition.metric_selections}
    periods_by_night = {night_id: period for period in definition.periods for night_id in period.night_record_ids}
    if any(value.metric_id not in metrics for value in values):
        raise GenericExperimentError("A generic experiment observation must use a preselected metric.")
    if any(value.night_record_id not in periods_by_night for value in values):
        raise GenericExperimentError("A generic experiment observation must belong to an explicitly assigned period night.")
    expected_pairs = {(metric_id, night_id) for metric_id in metrics for night_id in periods_by_night}
    actual_pairs = {(value.metric_id, value.night_record_id) for value in values}
    if actual_pairs != expected_pairs:
        raise GenericExperimentError("Every selected metric and assigned night requires an explicit calculated or insufficient observation.")
    if any(value.unit != metrics[value.metric_id].unit for value in values):
        raise GenericExperimentError("Generic metric-observation units must match their metric selections.")
    by_key = {(value.metric_id, value.night_record_id): value for value in values}
    summaries = tuple(
        _period_summary(metric, period, by_key)
        for metric in definition.metric_selections
        for period in definition.periods
    )
    summary_by_key = {(value.metric_id, value.period_id): value for value in summaries}
    reference = next(period for period in definition.periods if period.role is GenericExperimentPeriodRole.REFERENCE)
    comparisons = tuple(
        _comparison(metric.metric_id, reference, comparison, summary_by_key)
        for metric in definition.metric_selections
        for comparison in definition.periods
        if comparison.role is GenericExperimentPeriodRole.COMPARISON
    )
    calculated_comparisons = sum(value.status is GenericExperimentMetricStatus.CALCULATED for value in comparisons)
    if calculated_comparisons == len(comparisons):
        status = GenericExperimentAnalysisStatus.ANALYZED
    elif calculated_comparisons:
        status = GenericExperimentAnalysisStatus.PARTIAL
    else:
        status = GenericExperimentAnalysisStatus.NOT_EVALUABLE
    reasons = () if status is GenericExperimentAnalysisStatus.ANALYZED else tuple(sorted({reason for value in comparisons for reason in value.reason_codes}))
    ordered_values = tuple(sorted(values, key=lambda value: (value.metric_id, value.night_record_id, value.record_id)))
    identity = repr((definition, ordered_values))
    source_ids = tuple(sorted({definition.record_id, *definition.source_record_ids, *(value.record_id for value in values), *(identifier for value in values for identifier in value.source_record_ids)}))
    provenance_ids = tuple(sorted({*definition.source_provenance_ids, *(identifier for value in values for identifier in value.source_provenance_ids)}))
    return GenericExperimentAnalysis(
        record_id=f"generic-experiment-analysis:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        experiment_definition_id=definition.record_id,
        experiment_record_id=definition.experiment_record_id,
        status=status,
        period_summaries=summaries,
        comparisons=comparisons,
        metric_observation_ids=tuple(value.record_id for value in ordered_values),
        source_record_ids=source_ids,
        source_provenance_ids=provenance_ids,
        reason_codes=reasons,
        limitations=(
            "Comparisons are descriptive within this explicitly assigned experiment and do not establish causation, clinical significance, or safety.",
            "The generic analysis applies no outcome threshold, automatic classification, recommendation, or device action.",
        ),
    )


def dispatch_generic_experiment_safety(definition: GenericExperimentDefinition, policy_input: object | None = None) -> GenericExperimentSafetyResult:
    """Route prospective definitions to the closed registered policy set and fail closed."""

    _instance(definition, GenericExperimentDefinition, "generic experiment definition")
    if definition.mode is GenericExperimentMode.RETROSPECTIVE:
        return GenericExperimentSafetyResult(definition.record_id, GenericExperimentSafetyStatus.NOT_APPLICABLE, None, None, ("retrospective_analysis_has_no_prospective_action",), None)
    assert definition.safety_policy is not None
    policy = definition.safety_policy
    if (policy.policy_id, policy.policy_version) != (PROSPECTIVE_SAFETY_POLICY_ID, PROSPECTIVE_SAFETY_POLICY_VERSION):
        return GenericExperimentSafetyResult(definition.record_id, GenericExperimentSafetyStatus.POLICY_UNAVAILABLE, policy.policy_id, policy.policy_version, ("unsupported_safety_policy",), None)
    if not isinstance(policy_input, PsMinSafetyPolicyInput):
        return GenericExperimentSafetyResult(definition.record_id, GenericExperimentSafetyStatus.INELIGIBLE, policy.policy_id, policy.policy_version, ("missing_ps_min_policy_input",), None)
    change = definition.change
    proposal_change = policy_input.proposal.proposed_change
    if change.kind is not GenericExperimentVariableKind.DEVICE_SETTING or change.variable_id != proposal_change.previous.name or change.reference_value != proposal_change.previous.value or change.comparison_value != proposal_change.proposed.value or change.unit != proposal_change.previous.unit:
        return GenericExperimentSafetyResult(definition.record_id, GenericExperimentSafetyStatus.INELIGIBLE, policy.policy_id, policy.policy_version, ("policy_input_mismatch",), None)
    delegated = evaluate_prospective_safety(policy_input.proposal, policy_input.evidence)
    status = GenericExperimentSafetyStatus.ELIGIBLE if delegated.eligible else GenericExperimentSafetyStatus.INELIGIBLE
    return GenericExperimentSafetyResult(definition.record_id, status, delegated.policy_id, delegated.policy_version, tuple(code.value for code in delegated.failure_codes), delegated.engine_version)


def _period_summary(metric: GenericExperimentMetricSelection, period: GenericExperimentPeriod, observations: dict[tuple[str, str], GenericExperimentMetricObservation]) -> GenericExperimentPeriodSummary:
    selected = tuple(observations[(metric.metric_id, night_id)] for night_id in period.night_record_ids)
    calculated = tuple(value for value in selected if value.status is GenericExperimentMetricStatus.CALCULATED)
    missing = tuple(value for value in selected if value.status is GenericExperimentMetricStatus.INSUFFICIENT_EVIDENCE)
    numeric = tuple(value.value for value in calculated)
    enough = len(numeric) >= metric.minimum_calculated_nights_per_period
    reasons = () if enough else tuple(sorted({"minimum_calculated_nights_not_met", *(reason for value in missing for reason in value.reason_codes)}))
    return GenericExperimentPeriodSummary(
        metric_id=metric.metric_id,
        period_id=period.period_id,
        status=GenericExperimentMetricStatus.CALCULATED if enough else GenericExperimentMetricStatus.INSUFFICIENT_EVIDENCE,
        calculated_count=len(numeric),
        minimum=None if not enough else min(numeric),
        median=None if not enough else float(median(numeric)),
        maximum=None if not enough else max(numeric),
        observation_record_ids=tuple(value.record_id for value in calculated),
        insufficient_observation_record_ids=tuple(value.record_id for value in missing),
        reason_codes=reasons,
    )


def _comparison(metric_id: str, reference_period: GenericExperimentPeriod, comparison_period: GenericExperimentPeriod, summaries: dict[tuple[str, str], GenericExperimentPeriodSummary]) -> GenericExperimentComparison:
    reference = summaries[(metric_id, reference_period.period_id)]
    comparison = summaries[(metric_id, comparison_period.period_id)]
    if reference.status is GenericExperimentMetricStatus.CALCULATED and comparison.status is GenericExperimentMetricStatus.CALCULATED:
        assert reference.median is not None and comparison.median is not None
        return GenericExperimentComparison(metric_id, reference.period_id, comparison.period_id, GenericExperimentMetricStatus.CALCULATED, reference.median, comparison.median, comparison.median - reference.median, ())
    reasons = tuple(sorted({*(f"reference:{reason}" for reason in reference.reason_codes), *(f"comparison:{reason}" for reason in comparison.reason_codes)}))
    return GenericExperimentComparison(metric_id, reference.period_id, comparison.period_id, GenericExperimentMetricStatus.INSUFFICIENT_EVIDENCE, None, None, None, reasons)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GenericExperimentError(f"A {label} must be nonempty text.")
    return value


def _optional_text(value: object, label: str) -> None:
    if value is not None:
        _text(value, label)


def _value(value: object, label: str) -> None:
    if isinstance(value, bool) or isinstance(value, str):
        if isinstance(value, str):
            _text(value, label)
        return
    if type(value) in (int, float) and math.isfinite(float(value)):
        return
    raise GenericExperimentError(f"A {label} must be a finite scalar value.")


def _number(value: object, label: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise GenericExperimentError(f"A {label} must be finite numeric evidence.")


def _enum(value: object, enum_type: type[StrEnum], label: str) -> None:
    if not isinstance(value, enum_type):
        raise GenericExperimentError(f"A {label} is unsupported.")


def _instance(value: object, expected_type: type, label: str) -> None:
    if not isinstance(value, expected_type):
        raise GenericExperimentError(f"A {label} is required.")


def _typed_tuple(values: object, value_type: type, label: str, *, required: bool = False) -> tuple:
    if not isinstance(values, tuple) or any(not isinstance(value, value_type) for value in values) or (required and not values):
        raise GenericExperimentError(f"{label.capitalize()} must be an immutable{' nonempty' if required else ''} tuple of {value_type.__name__} records.")
    return values


def _texts(values: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(values, tuple) or (required and not values):
        raise GenericExperimentError(f"{label.capitalize()} must be an immutable{' nonempty' if required else ''} tuple.")
    for value in values:
        _text(value, label)
    _unique(values, label)
    return tuple(sorted(values))


def _identifiers(values: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    return _texts(values, label, required=required)


def _unique(values: tuple, label: str) -> None:
    if len(set(values)) != len(values):
        raise GenericExperimentError(f"{label.capitalize()} must be unique.")
