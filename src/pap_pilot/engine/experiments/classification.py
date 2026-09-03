"""Deterministic version-1 retrospective outcome classification."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
import hashlib
import math
from statistics import median
from typing import Final

from pap_pilot.engine.experiments.allocation import ExperimentNightAllocation, ExperimentPeriod
from pap_pilot.engine.experiments.journal import ConfounderReportStatus, SleepJournalEntry
from pap_pilot.engine.experiments.model import (
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentRevisedPayload,
    ObservationRecordedPayload,
    SettingChangeConfirmedPayload,
    SleepJournalEntryRecordedPayload,
)
from pap_pilot.engine.metrics import MetricId, MetricResult, MetricStatus
from pap_pilot.engine.model import SourceClass


OUTCOME_CLASSIFICATION_RULE_SET_ID: Final = "pap-pilot.ps-min-outcome-classification"
OUTCOME_CLASSIFICATION_RULE_SET_VERSION: Final = 1
OUTCOME_CLASSIFICATION_RECORD_VERSION: Final = 1
OUTCOME_CLASSIFICATION_ENGINE_VERSION: Final = "0.1.0"
MINIMUM_CLASSIFICATION_NIGHTS_PER_ARM: Final = 3
DIRECTION_CONSISTENCY_NUMERATOR: Final = 2
DIRECTION_CONSISTENCY_DENOMINATOR: Final = 3


class OutcomeClassificationError(ValueError):
    """Raised when classification inputs are not immutable supported records."""


class OutcomeId(StrEnum):
    """Every objective or subjective outcome in rule-set version 1."""

    MEAN_MASK_PRESSURE_ABOVE_EPAP = "mean_mask_pressure_above_epap"
    MINUTE_VENTILATION_UPPER_TAIL_RATIO = "minute_ventilation_upper_tail_ratio"
    AWAKENINGS_COUNT = "awakenings_count"
    SLEEP_QUALITY = "sleep_quality"
    MORNING_ENERGY = "morning_energy"
    DAYTIME_TIREDNESS = "daytime_tiredness"


class OutcomeDirection(StrEnum):
    """Direction treated as favorable by the bounded engineering rule set."""

    LOWER = "lower"
    HIGHER = "higher"


class OutcomeState(StrEnum):
    """One outcome's state after its evidence and consistency gates."""

    EXPECTED_MECHANISM = "expected_mechanism"
    UNEXPECTED_MECHANISM = "unexpected_mechanism"
    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    ADVERSE = "adverse"
    UNSTABLE = "unstable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SubjectiveDomainState(StrEnum):
    """Aggregation of the evaluable sleep-journal outcomes."""

    FAVORABLE = "favorable"
    ADVERSE = "adverse"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    WEAK_FAVORABLE = "weak_favorable"
    WEAK_ADVERSE = "weak_adverse"
    UNSTABLE = "unstable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ConfounderEvidenceStatus(StrEnum):
    """Whether reported confounders are balanced and sufficiently answered."""

    BALANCED = "balanced"
    IMBALANCED = "imbalanced"
    INSUFFICIENT_REPORTING = "insufficient_reporting"
    UNAVAILABLE = "unavailable"


class OutcomeClassification(StrEnum):
    """The six classifications fixed by the governing plan."""

    CLEAR_IMPROVEMENT = "clear_improvement"
    PROBABLE_IMPROVEMENT = "probable_improvement"
    MIXED_TRADEOFF = "mixed_tradeoff"
    NO_MEANINGFUL_CHANGE = "no_meaningful_change"
    PROBABLE_WORSENING = "probable_worsening"
    INCONCLUSIVE = "inconclusive"


class OutcomeAction(StrEnum):
    """Retrospective analytical next actions; none controls a PAP device."""

    KEEP = "keep"
    REVERT = "revert"
    EXTEND = "extend"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class OutcomeThreshold:
    """One prespecified engineering boundary."""

    outcome_id: OutcomeId
    magnitude: float
    unit: str
    favorable_direction: OutcomeDirection

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_id, OutcomeId) or not isinstance(self.favorable_direction, OutcomeDirection):
            raise OutcomeClassificationError("An outcome threshold requires supported outcome and direction values.")
        if type(self.magnitude) not in (int, float) or not math.isfinite(float(self.magnitude)) or self.magnitude <= 0:
            raise OutcomeClassificationError("An outcome threshold magnitude must be positive.")
        if type(self.unit) is not str or not self.unit.strip():
            raise OutcomeClassificationError("The outcome threshold unit must be nonempty text.")


OUTCOME_THRESHOLDS: Final = (
    OutcomeThreshold(OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP, 0.5, "cm H₂O", OutcomeDirection.LOWER),
    OutcomeThreshold(OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, 0.10, "1", OutcomeDirection.LOWER),
    OutcomeThreshold(OutcomeId.AWAKENINGS_COUNT, 1.0, "awakening", OutcomeDirection.LOWER),
    OutcomeThreshold(OutcomeId.SLEEP_QUALITY, 1.0, "scale point", OutcomeDirection.HIGHER),
    OutcomeThreshold(OutcomeId.MORNING_ENERGY, 1.0, "scale point", OutcomeDirection.HIGHER),
    OutcomeThreshold(OutcomeId.DAYTIME_TIREDNESS, 1.0, "scale point", OutcomeDirection.LOWER),
)
_THRESHOLD_BY_OUTCOME: Final = {value.outcome_id: value for value in OUTCOME_THRESHOLDS}
_SUBJECTIVE_OUTCOMES: Final = (
    OutcomeId.AWAKENINGS_COUNT,
    OutcomeId.SLEEP_QUALITY,
    OutcomeId.MORNING_ENERGY,
    OutcomeId.DAYTIME_TIREDNESS,
)
_SUBJECTIVE_ANCHORS: Final = {OutcomeId.SLEEP_QUALITY, OutcomeId.MORNING_ENERGY}
_RESOLVABLE_REASON_PREFIXES: Final = (
    "insufficient_baseline_nights",
    "insufficient_intervention_nights",
    "too_few_calculated_",
    "too_few_subjective_outcomes",
    "subjective_anchor_missing",
    "unstable_",
)
_LIMITATIONS: Final = (
    "This is an unblinded, nonrandomized, retrospective within-user engineering comparison and does not establish causality.",
    "The change boundaries are prespecified prototype engineering thresholds, not validated clinical cutoffs or minimal clinically important differences.",
    "Per-arm medians and median absolute deviations describe the retained nightly observations; no p-value or independent-observation claim is made.",
    "Journal free text is preserved as source evidence but is not parsed into an outcome, confounder, or adverse effect.",
    "Balanced reported confounders do not prove absence of confounding, and adverse-effect severity is not interpreted by this rule set.",
    "The next action is an evidence-record recommendation for manual review and never changes a PAP device.",
)


@dataclass(frozen=True, slots=True)
class NightlyOutcomeValue:
    """One outcome value linked to its night and evidence record."""

    night_record_id: str
    evidence_record_id: str
    value: float

    def __post_init__(self) -> None:
        _text(self.night_record_id, "outcome night identifier")
        _text(self.evidence_record_id, "outcome evidence identifier")
        _number(self.value, "nightly outcome value")


@dataclass(frozen=True, slots=True)
class OutcomeArmSummary:
    """One period's retained values and descriptive summary."""

    period: ExperimentPeriod
    values: tuple[NightlyOutcomeValue, ...]
    count: int
    minimum: float | None
    median: float | None
    maximum: float | None
    median_absolute_deviation: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod):
            raise OutcomeClassificationError("An outcome summary requires a supported experiment period.")
        values = _typed_tuple(self.values, NightlyOutcomeValue, "nightly outcome values")
        if type(self.count) is not int or self.count != len(values):
            raise OutcomeClassificationError("An outcome summary count must match its retained values.")
        if len({value.night_record_id for value in values}) != len(values):
            raise OutcomeClassificationError("An outcome summary requires at most one value per night.")
        statistics = (self.minimum, self.median, self.maximum, self.median_absolute_deviation)
        if values:
            if any(value is None for value in statistics):
                raise OutcomeClassificationError("A nonempty outcome summary requires every descriptive statistic.")
            for value in statistics:
                _number(value, "outcome summary statistic")
            raw = tuple(_decimal(value.value) for value in values)
            expected_median = median(raw)
            expected = (min(raw), expected_median, max(raw), median(tuple(abs(value - expected_median) for value in raw)))
            if tuple(_decimal(value) for value in statistics) != expected:
                raise OutcomeClassificationError("Outcome summary statistics must exactly describe the retained nightly values.")
        elif any(value is not None for value in statistics):
            raise OutcomeClassificationError("An empty outcome summary cannot carry descriptive statistics.")
        object.__setattr__(self, "values", tuple(sorted(values, key=lambda value: (value.night_record_id, value.evidence_record_id))))


@dataclass(frozen=True, slots=True)
class OutcomeEvidence:
    """One thresholded outcome with per-arm summaries and consistency evidence."""

    outcome_id: OutcomeId
    threshold: OutcomeThreshold
    baseline: OutcomeArmSummary
    intervention: OutcomeArmSummary
    delta: float | None
    state: OutcomeState
    direction_matching_count: int
    direction_total_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_id, OutcomeId) or self.threshold != _THRESHOLD_BY_OUTCOME.get(self.outcome_id):
            raise OutcomeClassificationError("Outcome evidence requires its exact version-1 threshold.")
        if self.baseline.period is not ExperimentPeriod.BASELINE or self.intervention.period is not ExperimentPeriod.INTERVENTION:
            raise OutcomeClassificationError("Outcome evidence summaries must retain baseline and intervention order.")
        if not isinstance(self.state, OutcomeState):
            raise OutcomeClassificationError("Outcome evidence has an unsupported state.")
        if self.delta is not None:
            _number(self.delta, "outcome median delta")
        if type(self.direction_matching_count) is not int or type(self.direction_total_count) is not int or not 0 <= self.direction_matching_count <= self.direction_total_count:
            raise OutcomeClassificationError("Outcome direction counts must be nonnegative and internally consistent.")
        if self.direction_total_count != self.intervention.count:
            raise OutcomeClassificationError("Outcome direction evidence must cover the retained intervention values.")


@dataclass(frozen=True, slots=True)
class ArmConfounderSummary:
    """Per-arm confounder and missing-answer counts."""

    period: ExperimentPeriod
    journaled_night_count: int
    confounded_night_count: int
    not_reported_night_count: int
    confounded_fraction: float | None
    not_reported_fraction: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.period, ExperimentPeriod):
            raise OutcomeClassificationError("A confounder summary requires a supported experiment period.")
        counts = (self.journaled_night_count, self.confounded_night_count, self.not_reported_night_count)
        if any(type(value) is not int or value < 0 for value in counts) or self.confounded_night_count > self.journaled_night_count or self.not_reported_night_count > self.journaled_night_count:
            raise OutcomeClassificationError("Confounder counts must be nonnegative and cannot exceed journaled nights.")
        fractions = (self.confounded_fraction, self.not_reported_fraction)
        if self.journaled_night_count == 0 and any(value is not None for value in fractions):
            raise OutcomeClassificationError("An empty confounder summary cannot carry fractions.")
        if self.journaled_night_count:
            if any(value is None for value in fractions):
                raise OutcomeClassificationError("A nonempty confounder summary requires fractions from zero through one.")
            for value in fractions:
                _number(value, "confounder fraction")
            expected = (self.confounded_night_count / self.journaled_night_count, self.not_reported_night_count / self.journaled_night_count)
            if fractions != expected:
                raise OutcomeClassificationError("Confounder fractions must exactly match their counts.")


@dataclass(frozen=True, slots=True)
class ConfounderEvidence:
    """Confounder balance derived without causal numerical adjustment."""

    baseline: ArmConfounderSummary
    intervention: ArmConfounderSummary
    status: ConfounderEvidenceStatus

    def __post_init__(self) -> None:
        if self.baseline.period is not ExperimentPeriod.BASELINE or self.intervention.period is not ExperimentPeriod.INTERVENTION:
            raise OutcomeClassificationError("Confounder evidence must retain baseline and intervention order.")
        if not isinstance(self.status, ConfounderEvidenceStatus):
            raise OutcomeClassificationError("Confounder evidence has an unsupported status.")
        if self.baseline.journaled_night_count == 0 or self.intervention.journaled_night_count == 0:
            expected = ConfounderEvidenceStatus.UNAVAILABLE
        elif 3 * self.baseline.not_reported_night_count > self.baseline.journaled_night_count or 3 * self.intervention.not_reported_night_count > self.intervention.journaled_night_count:
            expected = ConfounderEvidenceStatus.INSUFFICIENT_REPORTING
        else:
            difference = abs(Fraction(self.baseline.confounded_night_count, self.baseline.journaled_night_count) - Fraction(self.intervention.confounded_night_count, self.intervention.journaled_night_count))
            expected = ConfounderEvidenceStatus.IMBALANCED if difference >= Fraction(1, 3) else ConfounderEvidenceStatus.BALANCED
        if self.status is not expected:
            raise OutcomeClassificationError("Confounder evidence status must match the retained arm counts.")


@dataclass(frozen=True, slots=True)
class OutcomeClassificationResult:
    """Immutable, evidence-linked retrospective classification result."""

    record_id: str
    classification: OutcomeClassification
    action: OutcomeAction
    required_nights_per_arm: int
    baseline_included_night_count: int
    intervention_included_night_count: int
    outcomes: tuple[OutcomeEvidence, ...]
    subjective_domain_state: SubjectiveDomainState
    confounders: ConfounderEvidence
    adverse_effect_event_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    proposal_event_id: str
    acceptance_event_id: str
    setting_change_event_id: str
    allocation_record_id: str
    excluded_night_record_ids: tuple[str, ...]
    metric_result_ids: tuple[str, ...]
    journal_entry_ids: tuple[str, ...]
    experiment_event_ids: tuple[str, ...]
    quality_report_ids: tuple[str, ...]
    quality_finding_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    rule_set_id: str = OUTCOME_CLASSIFICATION_RULE_SET_ID
    rule_set_version: int = OUTCOME_CLASSIFICATION_RULE_SET_VERSION
    record_version: int = OUTCOME_CLASSIFICATION_RECORD_VERSION
    engine_version: str = OUTCOME_CLASSIFICATION_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "outcome-classification identifier")
        if not isinstance(self.classification, OutcomeClassification) or not isinstance(self.action, OutcomeAction):
            raise OutcomeClassificationError("A classification result requires supported classification and action values.")
        if type(self.required_nights_per_arm) is not int or self.required_nights_per_arm < MINIMUM_CLASSIFICATION_NIGHTS_PER_ARM:
            raise OutcomeClassificationError("A classification result requires the version-1 per-arm minimum.")
        for value in (self.baseline_included_night_count, self.intervention_included_night_count):
            if type(value) is not int or value < 0:
                raise OutcomeClassificationError("Included-night counts must be nonnegative integers.")
        outcomes = _typed_tuple(self.outcomes, OutcomeEvidence, "classification outcomes")
        if tuple(value.outcome_id for value in outcomes) != tuple(OutcomeId):
            raise OutcomeClassificationError("A classification result must retain every version-1 outcome in canonical order.")
        if not isinstance(self.subjective_domain_state, SubjectiveDomainState) or not isinstance(self.confounders, ConfounderEvidence):
            raise OutcomeClassificationError("A classification result requires subjective and confounder evidence.")
        for name in (
            "adverse_effect_event_ids",
            "reason_codes",
            "limitations",
            "excluded_night_record_ids",
            "metric_result_ids",
            "journal_entry_ids",
            "experiment_event_ids",
            "quality_report_ids",
            "quality_finding_ids",
            "source_record_ids",
            "source_provenance_ids",
        ):
            values = _text_tuple(getattr(self, name), name)
            if len(set(values)) != len(values):
                raise OutcomeClassificationError(f"The {name} must be unique.")
            object.__setattr__(self, name, tuple(sorted(values)))
        if not self.limitations or not self.source_record_ids or not self.source_provenance_ids:
            raise OutcomeClassificationError("A classification result requires limitations and source evidence.")
        for name in ("proposal_event_id", "acceptance_event_id", "setting_change_event_id", "allocation_record_id"):
            _text(getattr(self, name), name)
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise OutcomeClassificationError("Outcome classifications must be companion-derived.")
        expected_actions = {
            OutcomeClassification.CLEAR_IMPROVEMENT: OutcomeAction.KEEP,
            OutcomeClassification.PROBABLE_IMPROVEMENT: OutcomeAction.KEEP,
            OutcomeClassification.MIXED_TRADEOFF: OutcomeAction.INCONCLUSIVE,
            OutcomeClassification.NO_MEANINGFUL_CHANGE: OutcomeAction.REVERT,
            OutcomeClassification.PROBABLE_WORSENING: OutcomeAction.REVERT,
        }
        if self.classification in expected_actions and self.action is not expected_actions[self.classification]:
            raise OutcomeClassificationError("The classification and analytical action are incompatible.")
        if not set((self.proposal_event_id, self.acceptance_event_id, self.setting_change_event_id, *self.experiment_event_ids, *self.metric_result_ids, *self.journal_entry_ids, *self.quality_report_ids, *self.quality_finding_ids, *self.excluded_night_record_ids)).issubset(self.source_record_ids):
            raise OutcomeClassificationError("Classification source identifiers must cover all retained evidence identifiers.")
        if not set(self.adverse_effect_event_ids).issubset(self.experiment_event_ids):
            raise OutcomeClassificationError("Adverse-effect identifiers must be retained as experiment-event evidence.")
        expected_versions = (
            OUTCOME_CLASSIFICATION_RULE_SET_ID,
            OUTCOME_CLASSIFICATION_RULE_SET_VERSION,
            OUTCOME_CLASSIFICATION_RECORD_VERSION,
            OUTCOME_CLASSIFICATION_ENGINE_VERSION,
        )
        if (self.rule_set_id, self.rule_set_version, self.record_version, self.engine_version) != expected_versions:
            raise OutcomeClassificationError("The outcome-classification identity or version is unsupported.")
        object.__setattr__(self, "outcomes", outcomes)

    def outcome(self, outcome_id: OutcomeId) -> OutcomeEvidence:
        """Return one named outcome from the fixed version-1 set."""

        if not isinstance(outcome_id, OutcomeId):
            raise OutcomeClassificationError("An outcome query requires a supported outcome identifier.")
        return next(value for value in self.outcomes if value.outcome_id is outcome_id)


def evaluate_outcome_classification(
    proposal_event: ExperimentEvent,
    acceptance_event: ExperimentEvent,
    setting_change_event: ExperimentEvent,
    allocation: ExperimentNightAllocation,
    metric_results: tuple[MetricResult, ...],
    journal_entries: tuple[SleepJournalEntry, ...],
    evidence_events: tuple[ExperimentEvent, ...] = (),
) -> OutcomeClassificationResult:
    """Apply the accepted retrospective PS Min 2-to-1 classification contract."""

    proposal = _proposal(proposal_event)
    acceptance = _event_payload(acceptance_event, ExperimentEventType.EXPERIMENT_ACCEPTED, ExperimentDecisionPayload, "accepted proposal")
    confirmed = _event_payload(setting_change_event, ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED, SettingChangeConfirmedPayload, "confirmed setting change")
    if not isinstance(allocation, ExperimentNightAllocation):
        raise OutcomeClassificationError("Classification requires one ExperimentNightAllocation.")
    metrics = _typed_tuple(metric_results, MetricResult, "metric results")
    journals = _typed_tuple(journal_entries, SleepJournalEntry, "journal entries")
    evidence = _typed_tuple(evidence_events, ExperimentEvent, "evidence events")
    allowed_evidence_types = {ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED, ExperimentEventType.CONFOUNDER_RECORDED, ExperimentEventType.ADVERSE_EFFECT_RECORDED}
    if any(value.event_type not in allowed_evidence_types for value in evidence):
        raise OutcomeClassificationError("Classification evidence events must contain only journal references, confounders, or adverse effects.")
    observations = tuple(value for value in evidence if value.event_type in {ExperimentEventType.CONFOUNDER_RECORDED, ExperimentEventType.ADVERSE_EFFECT_RECORDED})
    journal_events = tuple(value for value in evidence if value.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED)

    required = max(MINIMUM_CLASSIFICATION_NIGHTS_PER_ARM, proposal.minimum_valid_nights)
    baseline_nights = allocation.included(ExperimentPeriod.BASELINE)
    intervention_nights = allocation.included(ExperimentPeriod.INTERVENTION)
    included_by_id = {value.night_record_id: value.period for value in (*baseline_nights, *intervention_nights)}
    allocated_ids = {value.night_record_id for value in allocation.nights}
    reasons: list[str] = []

    if len({value.record_id for value in (proposal_event, acceptance_event, setting_change_event, *evidence)}) != 3 + len(evidence):
        reasons.append("duplicate_experiment_event_id")
    if len({value.record_id for value in metrics}) != len(metrics):
        reasons.append("duplicate_metric_result_id")
    if len({value.record_id for value in journals}) != len(journals):
        reasons.append("duplicate_journal_entry_id")

    experiment_ids = {proposal_event.experiment_record_id, acceptance_event.experiment_record_id, setting_change_event.experiment_record_id, *(value.experiment_record_id for value in evidence)}
    if len(experiment_ids) != 1:
        reasons.append("experiment_event_linkage_mismatch")
    if acceptance.proposal_event_id != proposal_event.record_id:
        reasons.append("proposal_acceptance_linkage_mismatch")
    if confirmed.accepted_event_id != acceptance_event.record_id:
        reasons.append("acceptance_setting_change_linkage_mismatch")
    if confirmed.applied_change != proposal.proposed_change:
        reasons.append("confirmed_setting_change_mismatch")
    if allocation.setting_change_event_id != setting_change_event.record_id or allocation.applied_at_ms != confirmed.applied_at_ms:
        reasons.append("allocation_setting_change_linkage_mismatch")
    if not _supported_scope(proposal):
        reasons.append("unsupported_experiment_scope")
    if len(baseline_nights) < required:
        reasons.append("insufficient_baseline_nights")
    if len(intervention_nights) < required:
        reasons.append("insufficient_intervention_nights")

    metric_by_key: dict[tuple[str, MetricId], MetricResult] = {}
    for result in metrics:
        key = (result.night_record_id, result.metric_id)
        if result.night_record_id not in allocated_ids:
            reasons.append("metric_night_not_allocated")
        elif result.night_record_id in included_by_id and result.status is MetricStatus.CALCULATED:
            if result.night_record_id not in result.source_record_ids:
                reasons.append("metric_source_linkage_missing")
            if not _metric_settings_match(result, included_by_id[result.night_record_id], proposal):
                reasons.append("metric_setting_context_mismatch")
        if key in metric_by_key:
            reasons.append("duplicate_metric_result")
        metric_by_key[key] = result

    journal_by_night: dict[str, SleepJournalEntry] = {}
    for entry in journals:
        if entry.night_record_id not in allocated_ids:
            reasons.append("journal_night_not_allocated")
        if entry.night_record_id in journal_by_night:
            reasons.append("duplicate_journal_entry")
        journal_by_night[entry.night_record_id] = entry

    journal_by_id = {value.record_id: value for value in journals}
    journal_event_counts: dict[str, int] = {}
    for event in journal_events:
        if not isinstance(event.payload, SleepJournalEntryRecordedPayload):
            raise OutcomeClassificationError("A journal evidence event requires its journal-reference payload.")
        entry = journal_by_id.get(event.payload.journal_entry_record_id)
        if entry is None:
            reasons.append("journal_event_entry_missing")
        elif entry.night_record_id != event.payload.night_record_id:
            reasons.append("journal_event_night_linkage_mismatch")
        journal_event_counts[event.payload.journal_entry_record_id] = journal_event_counts.get(event.payload.journal_entry_record_id, 0) + 1
    if any(journal_event_counts.get(entry.record_id, 0) == 0 for entry in journals):
        reasons.append("journal_entry_event_missing")
    if any(count > 1 for count in journal_event_counts.values()):
        reasons.append("duplicate_journal_reference_event")

    confounder_events_by_night: dict[str, list[ExperimentEvent]] = {}
    adverse_events = tuple(value for value in observations if value.event_type is ExperimentEventType.ADVERSE_EFFECT_RECORDED)
    for event in observations:
        if event.event_type is not ExperimentEventType.CONFOUNDER_RECORDED:
            continue
        assert isinstance(event.payload, ObservationRecordedPayload)
        if event.payload.night_record_id is None:
            reasons.append("confounder_event_without_night")
        elif event.payload.night_record_id not in allocated_ids:
            reasons.append("observation_night_not_allocated")
        elif event.payload.night_record_id in included_by_id and event.payload.night_record_id not in journal_by_night:
            reasons.append("confounder_event_without_journal")
        else:
            confounder_events_by_night.setdefault(event.payload.night_record_id, []).append(event)

    outcomes = []
    objective_map = {
        OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP: MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP,
        OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO: MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO,
    }
    for outcome_id in OutcomeId:
        baseline_values: tuple[NightlyOutcomeValue, ...]
        intervention_values: tuple[NightlyOutcomeValue, ...]
        if outcome_id in objective_map:
            metric_id = objective_map[outcome_id]
            baseline_values = _metric_values(baseline_nights, metric_id, metric_by_key)
            intervention_values = _metric_values(intervention_nights, metric_id, metric_by_key)
            if len(baseline_values) < required:
                reasons.append(f"too_few_calculated_{outcome_id.value}_baseline")
            if len(intervention_values) < required:
                reasons.append(f"too_few_calculated_{outcome_id.value}_intervention")
        else:
            baseline_values = _journal_values(baseline_nights, outcome_id, journal_by_night)
            intervention_values = _journal_values(intervention_nights, outcome_id, journal_by_night)
        outcomes.append(_outcome_evidence(outcome_id, baseline_values, intervention_values, required))

    subjective, subjective_reasons = _subjective_domain(tuple(outcomes))
    reasons.extend(subjective_reasons)
    for outcome in outcomes:
        if outcome.state is OutcomeState.UNSTABLE:
            reasons.append(f"unstable_{outcome.outcome_id.value}")

    confounders = _confounder_evidence(baseline_nights, intervention_nights, journal_by_night, confounder_events_by_night)
    if confounders.status is ConfounderEvidenceStatus.INSUFFICIENT_REPORTING:
        reasons.append("confounder_reporting_insufficient")

    blocking_reasons = tuple(sorted(set(reasons)))
    classification, classification_reason = _classification(tuple(outcomes), subjective, confounders.status, bool(adverse_events), blocking_reasons)
    if classification_reason is not None:
        reasons.append(classification_reason)
    final_reasons = tuple(sorted(set(reasons)))
    action = _action(classification, final_reasons, bool(adverse_events))

    quality_report_ids = tuple(sorted({identifier for result in metrics for identifier in result.quality_report_ids} | {value.structural_quality_report_id for value in allocation.nights} | {identifier for value in allocation.nights for identifier in value.signal_quality_report_ids}))
    quality_finding_ids = tuple(sorted({identifier for result in metrics for identifier in result.quality_finding_ids} | {identifier for value in allocation.nights for identifier in value.quality_finding_ids}))
    source_records = {
        proposal_event.record_id,
        acceptance_event.record_id,
        setting_change_event.record_id,
        allocation.record_id,
        *(value.record_id for value in allocation.nights),
        *(value.night_record_id for value in allocation.nights),
        *(value.record_id for value in metrics),
        *(value.record_id for value in journals),
        *(value.record_id for value in evidence),
        *(identifier for event in (proposal_event, acceptance_event, setting_change_event, *evidence) for identifier in event.source_record_ids),
        *(identifier for result in metrics for identifier in result.source_record_ids),
        *(value.night_record_id for value in journals),
        *proposal.evidence_record_ids,
        *quality_report_ids,
        *quality_finding_ids,
    }
    source_provenance = {
        *(identifier for event in (proposal_event, acceptance_event, setting_change_event, *evidence) for identifier in event.source_provenance_ids),
        *(identifier for result in metrics for identifier in result.source_provenance_ids),
        *(identifier for entry in journals for identifier in entry.source_provenance_ids),
    }
    identity = (
        proposal_event.record_id,
        acceptance_event.record_id,
        setting_change_event.record_id,
        allocation.record_id,
        required,
        tuple(outcomes),
        subjective,
        confounders,
        tuple(sorted(value.record_id for value in adverse_events)),
        classification,
        action,
        final_reasons,
        tuple(sorted(source_records)),
        tuple(sorted(source_provenance)),
    )
    return OutcomeClassificationResult(
        record_id=f"outcome-classification:{hashlib.sha256(repr(identity).encode()).hexdigest()[:20]}",
        classification=classification,
        action=action,
        required_nights_per_arm=required,
        baseline_included_night_count=len(baseline_nights),
        intervention_included_night_count=len(intervention_nights),
        outcomes=tuple(outcomes),
        subjective_domain_state=subjective,
        confounders=confounders,
        adverse_effect_event_ids=tuple(sorted({value.record_id for value in adverse_events})),
        reason_codes=final_reasons,
        limitations=_LIMITATIONS,
        proposal_event_id=proposal_event.record_id,
        acceptance_event_id=acceptance_event.record_id,
        setting_change_event_id=setting_change_event.record_id,
        allocation_record_id=allocation.record_id,
        excluded_night_record_ids=tuple(value.night_record_id for value in allocation.excluded),
        metric_result_ids=tuple(sorted({value.record_id for value in metrics})),
        journal_entry_ids=tuple(sorted({value.record_id for value in journals})),
        experiment_event_ids=tuple(sorted({value.record_id for value in (proposal_event, acceptance_event, setting_change_event, *evidence)})),
        quality_report_ids=quality_report_ids,
        quality_finding_ids=quality_finding_ids,
        source_record_ids=tuple(source_records),
        source_provenance_ids=tuple(source_provenance),
    )


def _proposal(event: object) -> ExperimentProposal:
    if not isinstance(event, ExperimentEvent):
        raise OutcomeClassificationError("Classification requires one effective proposal event.")
    if event.event_type is ExperimentEventType.EXPERIMENT_PROPOSED and isinstance(event.payload, ExperimentProposedPayload):
        return event.payload.proposal
    if event.event_type is ExperimentEventType.EXPERIMENT_REVISED and isinstance(event.payload, ExperimentRevisedPayload):
        return event.payload.proposal
    raise OutcomeClassificationError("Classification requires an effective proposed or revised proposal event.")


def _event_payload(event: object, event_type: ExperimentEventType, payload_type: type, label: str):
    if not isinstance(event, ExperimentEvent) or event.event_type is not event_type or not isinstance(event.payload, payload_type):
        raise OutcomeClassificationError(f"Classification requires one effective {label} event.")
    return event.payload


def _supported_scope(proposal: ExperimentProposal) -> bool:
    change = proposal.proposed_change
    baseline = {value.name: value for value in proposal.baseline_settings}
    held = {value.name: value for value in proposal.settings_held_fixed}
    required = {"therapy_mode_code", "loader_mode_code", "epap", "ps_min", "ps_max", "max_ipap"}
    pressure_names = {"epap", "ps_min", "ps_max", "max_ipap"}
    if set(baseline) != required or set(held) != required - {"ps_min"}:
        return False
    if any(type(baseline[name].value) not in (int, float) or not math.isfinite(float(baseline[name].value)) or baseline[name].unit != "cm H₂O" for name in pressure_names):
        return False
    return (
        change.previous.name == "ps_min"
        and change.previous.value == 2.0
        and change.proposed.value == 1.0
        and change.previous.unit == "cm H₂O"
        and baseline["therapy_mode_code"].value == 6
        and baseline["therapy_mode_code"].unit is None
        and baseline["loader_mode_code"].value == 7
        and baseline["loader_mode_code"].unit is None
        and float(baseline["ps_min"].value) <= float(baseline["ps_max"].value)
        and math.isclose(float(baseline["max_ipap"].value), float(baseline["epap"].value) + float(baseline["ps_max"].value), rel_tol=0.0, abs_tol=1e-12)
    )


def _metric_values(nights, metric_id: MetricId, results: dict[tuple[str, MetricId], MetricResult]) -> tuple[NightlyOutcomeValue, ...]:
    values = []
    for night in nights:
        result = results.get((night.night_record_id, metric_id))
        if result is not None and result.status is MetricStatus.CALCULATED:
            assert result.value is not None
            values.append(NightlyOutcomeValue(night.night_record_id, result.record_id, result.value))
    return tuple(values)


def _metric_settings_match(result: MetricResult, period: ExperimentPeriod, proposal: ExperimentProposal) -> bool:
    expected = {value.name: (value.value, value.unit) for value in proposal.baseline_settings}
    if period is ExperimentPeriod.INTERVENTION:
        expected[proposal.proposed_change.proposed.name] = (proposal.proposed_change.proposed.value, proposal.proposed_change.proposed.unit)
    by_session: dict[str, dict[str, tuple[int | float, str | None]]] = {}
    for setting in result.settings:
        by_session.setdefault(setting.session_record_id, {})[setting.name] = (setting.value, setting.unit)
    return set(by_session) == set(result.session_record_ids) and all(values == expected for values in by_session.values())


def _journal_values(nights, outcome_id: OutcomeId, entries: dict[str, SleepJournalEntry]) -> tuple[NightlyOutcomeValue, ...]:
    values = []
    for night in nights:
        entry = entries.get(night.night_record_id)
        if entry is None:
            continue
        raw = getattr(entry, outcome_id.value)
        if raw is not None:
            values.append(NightlyOutcomeValue(night.night_record_id, entry.record_id, float(raw)))
    return tuple(values)


def _outcome_evidence(outcome_id: OutcomeId, baseline_values: tuple[NightlyOutcomeValue, ...], intervention_values: tuple[NightlyOutcomeValue, ...], required: int) -> OutcomeEvidence:
    threshold = _THRESHOLD_BY_OUTCOME[outcome_id]
    baseline = _summary(ExperimentPeriod.BASELINE, baseline_values)
    intervention = _summary(ExperimentPeriod.INTERVENTION, intervention_values)
    delta = None if baseline.median is None or intervention.median is None else float(_decimal(intervention.median) - _decimal(baseline.median))
    if baseline.count < required or intervention.count < required:
        return OutcomeEvidence(outcome_id, threshold, baseline, intervention, delta, OutcomeState.INSUFFICIENT_EVIDENCE, 0, intervention.count)
    assert baseline.median is not None and intervention.median is not None and delta is not None
    exact_delta = _decimal(intervention.median) - _decimal(baseline.median)
    boundary = _decimal(threshold.magnitude)
    if abs(exact_delta) < boundary:
        return OutcomeEvidence(outcome_id, threshold, baseline, intervention, delta, OutcomeState.NEUTRAL, 0, intervention.count)
    favorable = exact_delta < 0 if threshold.favorable_direction is OutcomeDirection.LOWER else exact_delta > 0
    baseline_median = _decimal(baseline.median)
    matching = sum(
        (_decimal(value.value) < baseline_median if threshold.favorable_direction is OutcomeDirection.LOWER else _decimal(value.value) > baseline_median)
        if favorable
        else (_decimal(value.value) > baseline_median if threshold.favorable_direction is OutcomeDirection.LOWER else _decimal(value.value) < baseline_median)
        for value in intervention.values
    )
    consistent = DIRECTION_CONSISTENCY_DENOMINATOR * matching >= DIRECTION_CONSISTENCY_NUMERATOR * intervention.count
    if not consistent:
        state = OutcomeState.UNSTABLE
    elif outcome_id is OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP:
        state = OutcomeState.EXPECTED_MECHANISM if favorable else OutcomeState.UNEXPECTED_MECHANISM
    else:
        state = OutcomeState.FAVORABLE if favorable else OutcomeState.ADVERSE
    return OutcomeEvidence(outcome_id, threshold, baseline, intervention, delta, state, matching, intervention.count)


def _summary(period: ExperimentPeriod, values: tuple[NightlyOutcomeValue, ...]) -> OutcomeArmSummary:
    if not values:
        return OutcomeArmSummary(period, (), 0, None, None, None, None)
    decimals = tuple(_decimal(value.value) for value in values)
    center = median(decimals)
    deviation = median(tuple(abs(value - center) for value in decimals))
    return OutcomeArmSummary(period, values, len(values), float(min(decimals)), float(center), float(max(decimals)), float(deviation))


def _subjective_domain(outcomes: tuple[OutcomeEvidence, ...]) -> tuple[SubjectiveDomainState, tuple[str, ...]]:
    subjective = tuple(value for value in outcomes if value.outcome_id in _SUBJECTIVE_OUTCOMES and value.state is not OutcomeState.INSUFFICIENT_EVIDENCE)
    reasons = []
    if len(subjective) < 2:
        reasons.append("too_few_subjective_outcomes")
    if not any(value.outcome_id in _SUBJECTIVE_ANCHORS for value in subjective):
        reasons.append("subjective_anchor_missing")
    if reasons:
        return SubjectiveDomainState.INSUFFICIENT_EVIDENCE, tuple(reasons)
    if any(value.state is OutcomeState.UNSTABLE for value in subjective):
        return SubjectiveDomainState.UNSTABLE, ()
    favorable = sum(value.state is OutcomeState.FAVORABLE for value in subjective)
    adverse = sum(value.state is OutcomeState.ADVERSE for value in subjective)
    if favorable and adverse:
        return SubjectiveDomainState.MIXED, ()
    if favorable >= 2:
        return SubjectiveDomainState.FAVORABLE, ()
    if adverse >= 2:
        return SubjectiveDomainState.ADVERSE, ()
    if all(value.state is OutcomeState.NEUTRAL for value in subjective):
        return SubjectiveDomainState.NEUTRAL, ()
    if favorable == 1:
        return SubjectiveDomainState.WEAK_FAVORABLE, ()
    if adverse == 1:
        return SubjectiveDomainState.WEAK_ADVERSE, ()
    return SubjectiveDomainState.INSUFFICIENT_EVIDENCE, ("unmatched_subjective_pattern",)


def _confounder_evidence(baseline_nights, intervention_nights, entries: dict[str, SleepJournalEntry], events: dict[str, list[ExperimentEvent]]) -> ConfounderEvidence:
    baseline = _arm_confounders(ExperimentPeriod.BASELINE, baseline_nights, entries, events)
    intervention = _arm_confounders(ExperimentPeriod.INTERVENTION, intervention_nights, entries, events)
    if baseline.journaled_night_count == 0 or intervention.journaled_night_count == 0:
        status = ConfounderEvidenceStatus.UNAVAILABLE
    elif 3 * baseline.not_reported_night_count > baseline.journaled_night_count or 3 * intervention.not_reported_night_count > intervention.journaled_night_count:
        status = ConfounderEvidenceStatus.INSUFFICIENT_REPORTING
    else:
        difference = abs(Fraction(baseline.confounded_night_count, baseline.journaled_night_count) - Fraction(intervention.confounded_night_count, intervention.journaled_night_count))
        status = ConfounderEvidenceStatus.IMBALANCED if difference >= Fraction(1, 3) else ConfounderEvidenceStatus.BALANCED
    return ConfounderEvidence(baseline, intervention, status)


def _arm_confounders(period: ExperimentPeriod, nights, entries: dict[str, SleepJournalEntry], events: dict[str, list[ExperimentEvent]]) -> ArmConfounderSummary:
    journaled = tuple(night.night_record_id for night in nights if night.night_record_id in entries)
    confounded = sum(bool(entries[night_id].confounders) or bool(events.get(night_id)) for night_id in journaled)
    not_reported = sum(entries[night_id].confounder_status is ConfounderReportStatus.NOT_REPORTED and not events.get(night_id) for night_id in journaled)
    total = len(journaled)
    return ArmConfounderSummary(period, total, confounded, not_reported, None if total == 0 else confounded / total, None if total == 0 else not_reported / total)


def _classification(outcomes: tuple[OutcomeEvidence, ...], subjective: SubjectiveDomainState, confounder_status: ConfounderEvidenceStatus, adverse_effect: bool, blocking_reasons: tuple[str, ...]) -> tuple[OutcomeClassification, str | None]:
    pressure = next(value.state for value in outcomes if value.outcome_id is OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP)
    ventilation = next(value.state for value in outcomes if value.outcome_id is OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO)
    if blocking_reasons:
        return OutcomeClassification.INCONCLUSIVE, None
    favorable = (pressure is OutcomeState.EXPECTED_MECHANISM) + (ventilation is OutcomeState.FAVORABLE) + (subjective in {SubjectiveDomainState.FAVORABLE, SubjectiveDomainState.MIXED})
    adverse = (pressure is OutcomeState.UNEXPECTED_MECHANISM) + (ventilation is OutcomeState.ADVERSE) + (subjective in {SubjectiveDomainState.ADVERSE, SubjectiveDomainState.MIXED}) + adverse_effect
    if favorable and adverse:
        return OutcomeClassification.MIXED_TRADEOFF, None
    clear = pressure is OutcomeState.EXPECTED_MECHANISM and ventilation in {OutcomeState.FAVORABLE, OutcomeState.NEUTRAL} and subjective is SubjectiveDomainState.FAVORABLE and not adverse_effect
    if clear:
        return (OutcomeClassification.PROBABLE_IMPROVEMENT, "confounder_imbalance_clear_downgrade") if confounder_status is ConfounderEvidenceStatus.IMBALANCED else (OutcomeClassification.CLEAR_IMPROVEMENT, None)
    if favorable >= 2 and not adverse:
        return (OutcomeClassification.INCONCLUSIVE, "confounder_imbalance_directional") if confounder_status is ConfounderEvidenceStatus.IMBALANCED else (OutcomeClassification.PROBABLE_IMPROVEMENT, None)
    if (adverse >= 2 and not favorable) or (adverse_effect and not favorable):
        return (OutcomeClassification.INCONCLUSIVE, "confounder_imbalance_directional") if confounder_status is ConfounderEvidenceStatus.IMBALANCED else (OutcomeClassification.PROBABLE_WORSENING, None)
    if pressure is OutcomeState.NEUTRAL and ventilation is OutcomeState.NEUTRAL and subjective is SubjectiveDomainState.NEUTRAL and not adverse_effect:
        return OutcomeClassification.NO_MEANINGFUL_CHANGE, None
    return OutcomeClassification.INCONCLUSIVE, "unmatched_signal_pattern"


def _action(classification: OutcomeClassification, reasons: tuple[str, ...], adverse_effect: bool) -> OutcomeAction:
    if classification in {OutcomeClassification.CLEAR_IMPROVEMENT, OutcomeClassification.PROBABLE_IMPROVEMENT}:
        return OutcomeAction.KEEP
    if classification in {OutcomeClassification.PROBABLE_WORSENING, OutcomeClassification.NO_MEANINGFUL_CHANGE}:
        return OutcomeAction.REVERT
    if classification is OutcomeClassification.MIXED_TRADEOFF:
        return OutcomeAction.INCONCLUSIVE
    if reasons and not adverse_effect and all(any(reason.startswith(prefix) for prefix in _RESOLVABLE_REASON_PREFIXES) for reason in reasons):
        return OutcomeAction.EXTEND
    return OutcomeAction.INCONCLUSIVE


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise OutcomeClassificationError(f"The {label} must be nonempty text.")


def _number(value: object, label: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise OutcomeClassificationError(f"The {label} must be a finite number.")


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str or not item.strip() for item in value):
        raise OutcomeClassificationError(f"The {label} must be an immutable text tuple.")
    return value


def _typed_tuple(value: object, expected: type, label: str) -> tuple:
    if type(value) is not tuple or any(not isinstance(item, expected) for item in value):
        raise OutcomeClassificationError(f"The {label} must be an immutable tuple of {expected.__name__} records.")
    return value
