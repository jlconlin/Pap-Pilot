"""Safe reconstruction of the known retrospective PS Min experiment."""

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Final

from pap_pilot.engine.experiments.allocation import ExperimentNightAllocation
from pap_pilot.engine.experiments.classification import OutcomeClassificationResult
from pap_pilot.engine.experiments.journal import SleepJournalEntry
from pap_pilot.engine.experiments.model import (
    ExperimentEvent,
    ExperimentEventType,
    ExperimentRecord,
    ExperimentSetting,
    ExperimentSettingChange,
    HypothesisDraftedPayload,
    ProblemRecordedPayload,
    validate_experiment_history,
)
from pap_pilot.engine.metrics import METRIC_SET_ID, METRIC_SET_VERSION, MetricResult
from pap_pilot.engine.model import NightRecord, SourceClass
from pap_pilot.engine.quality import SignalQualityReport, StructuralQualityReport


PS_MIN_RETROSPECTIVE_FIXTURE_ID: Final = "pap-pilot.ps-min-retrospective"
PS_MIN_RETROSPECTIVE_FIXTURE_VERSION: Final = 1
PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION: Final = 1
PS_MIN_RETROSPECTIVE_FIXTURE_ENGINE_VERSION: Final = "0.1.0"

_PLAN_PURPOSE_SOURCE: Final = "Plan.md#part-i-section-2"
_PLAN_VERTICAL_SLICE_SOURCE: Final = "Plan.md#part-i-section-9"
_METRIC_DECISION_SOURCE: Final = "docs/decisions/0004-initial-objective-metrics.md"
_JOURNAL_DECISION_SOURCE: Final = "docs/decisions/0005-sleep-journal-schema.md"
_CLASSIFICATION_DECISION_SOURCE: Final = "docs/decisions/0006-outcome-classification-rules.md"
_STATUS_BLOCKER_SOURCE: Final = "STATUS.md#blockers"
_FIXTURE_PROVENANCE_IDS: Final = (
    "provenance:decision:initial-objective-metrics-v1",
    "provenance:decision:outcome-classification-v1",
    "provenance:plan:personal-prototype",
)


class RetrospectiveFixtureError(ValueError):
    """Raised when the retained retrospective fixture is internally inconsistent."""


class RetrospectiveFixtureEvaluationStatus(StrEnum):
    """Whether the retained evidence can be passed to the outcome classifier."""

    NOT_EVALUABLE_WITHOUT_FABRICATION = "not_evaluable_without_fabrication"


class RetrospectiveMissingInputId(StrEnum):
    """Required retrospective inputs that are absent from the retained record."""

    ACCEPTED_PROPOSAL = "accepted_proposal"
    APPLIED_CHANGE_BOUNDARY = "applied_change_boundary"
    BASELINE_INTERVENTION_NIGHTS = "baseline_intervention_nights"
    QUALITY_REPORTS = "quality_reports"
    OBJECTIVE_METRIC_RESULTS = "objective_metric_results"
    STRUCTURED_JOURNAL_REPORTS = "structured_journal_reports"
    CONFOUNDER_ADVERSE_EFFECT_EVIDENCE = "confounder_adverse_effect_evidence"
    REPRESENTATIVE_INTERVALS = "representative_intervals"


@dataclass(frozen=True, slots=True)
class RetrospectiveKnownFact:
    """One bounded fact that is actually present in the governing record."""

    record_id: str
    statement: str
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.record_id, "known-fact identifier")
        _text(self.statement, "known-fact statement")
        sources = _text_tuple(self.source_record_ids, "known-fact source identifiers", required=True)
        _unique(sources, "known-fact source identifiers")
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


@dataclass(frozen=True, slots=True)
class RetrospectiveMissingInput:
    """One absent input and the deterministic work it prevents."""

    input_id: RetrospectiveMissingInputId
    description: str
    blocks: tuple[str, ...]
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.input_id, RetrospectiveMissingInputId):
            raise RetrospectiveFixtureError("A missing-input record requires a supported identifier.")
        _text(self.description, "missing-input description")
        blocks = _text_tuple(self.blocks, "blocked operations", required=True)
        sources = _text_tuple(self.source_record_ids, "missing-input source identifiers", required=True)
        _unique(blocks, "blocked operations")
        _unique(sources, "missing-input source identifiers")
        object.__setattr__(self, "blocks", tuple(sorted(blocks)))
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


@dataclass(frozen=True, slots=True)
class RetrospectiveFixtureEvaluation:
    """Deterministic readiness result that refuses to manufacture outcome evidence."""

    record_id: str
    status: RetrospectiveFixtureEvaluationStatus
    reason_codes: tuple[str, ...]
    missing_input_ids: tuple[RetrospectiveMissingInputId, ...]
    source_record_ids: tuple[str, ...]
    outcome_classification_record_id: str | None = None
    record_version: int = PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION
    engine_version: str = PS_MIN_RETROSPECTIVE_FIXTURE_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "fixture-evaluation identifier")
        if self.status is not RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION:
            raise RetrospectiveFixtureError("The version-1 fixture has an unsupported evaluation status.")
        reasons = _text_tuple(self.reason_codes, "fixture-evaluation reason codes", required=True)
        _unique(reasons, "fixture-evaluation reason codes")
        if type(self.missing_input_ids) is not tuple or not self.missing_input_ids or any(not isinstance(value, RetrospectiveMissingInputId) for value in self.missing_input_ids):
            raise RetrospectiveFixtureError("A fixture evaluation requires immutable missing-input identifiers.")
        if len(set(self.missing_input_ids)) != len(self.missing_input_ids):
            raise RetrospectiveFixtureError("Fixture-evaluation missing-input identifiers must be unique.")
        sources = _text_tuple(self.source_record_ids, "fixture-evaluation source identifiers", required=True)
        _unique(sources, "fixture-evaluation source identifiers")
        if self.outcome_classification_record_id is not None:
            raise RetrospectiveFixtureError("The incomplete version-1 fixture cannot reference an issued outcome classification.")
        if (self.record_version, self.engine_version) != (PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION, PS_MIN_RETROSPECTIVE_FIXTURE_ENGINE_VERSION):
            raise RetrospectiveFixtureError("The fixture-evaluation record or engine version is unsupported.")
        object.__setattr__(self, "reason_codes", tuple(sorted(reasons)))
        object.__setattr__(self, "missing_input_ids", tuple(sorted(self.missing_input_ids, key=lambda value: value.value)))
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


@dataclass(frozen=True, slots=True)
class PSMinRetrospectiveFixture:
    """The replayable known record plus explicit absent analytical inputs."""

    record_id: str
    experiment: ExperimentRecord
    history: tuple[ExperimentEvent, ...]
    known_change: ExperimentSettingChange
    known_facts: tuple[RetrospectiveKnownFact, ...]
    missing_inputs: tuple[RetrospectiveMissingInput, ...]
    normalized_nights: tuple[NightRecord, ...]
    structural_quality_reports: tuple[StructuralQualityReport, ...]
    signal_quality_reports: tuple[SignalQualityReport, ...]
    allocation: ExperimentNightAllocation | None
    metric_results: tuple[MetricResult, ...]
    journal_entries: tuple[SleepJournalEntry, ...]
    evidence_events: tuple[ExperimentEvent, ...]
    outcome_classification: OutcomeClassificationResult | None
    evaluation: RetrospectiveFixtureEvaluation
    limitations: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    fixture_id: str = PS_MIN_RETROSPECTIVE_FIXTURE_ID
    fixture_version: int = PS_MIN_RETROSPECTIVE_FIXTURE_VERSION
    record_version: int = PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "retrospective-fixture record identifier")
        if not isinstance(self.experiment, ExperimentRecord):
            raise RetrospectiveFixtureError("A retrospective fixture requires an experiment identity.")
        history = validate_experiment_history(self.experiment, self.history)
        if not isinstance(self.known_change, ExperimentSettingChange):
            raise RetrospectiveFixtureError("A retrospective fixture requires the known PS Min setting change.")
        facts = _typed_tuple(self.known_facts, RetrospectiveKnownFact, "known facts", required=True)
        missing = _typed_tuple(self.missing_inputs, RetrospectiveMissingInput, "missing inputs", required=True)
        if len({value.record_id for value in facts}) != len(facts) or len({value.input_id for value in missing}) != len(missing):
            raise RetrospectiveFixtureError("Known facts and missing inputs must have unique identifiers.")
        for values, value_type, label in (
            (self.normalized_nights, NightRecord, "normalized nights"),
            (self.structural_quality_reports, StructuralQualityReport, "structural quality reports"),
            (self.signal_quality_reports, SignalQualityReport, "signal quality reports"),
            (self.metric_results, MetricResult, "metric results"),
            (self.journal_entries, SleepJournalEntry, "journal entries"),
            (self.evidence_events, ExperimentEvent, "evidence events"),
        ):
            _typed_tuple(values, value_type, label)
        if self.allocation is not None or self.outcome_classification is not None:
            raise RetrospectiveFixtureError("The version-1 retained fixture cannot contain an allocation or outcome classification without its missing source evidence.")
        if any((self.normalized_nights, self.structural_quality_reports, self.signal_quality_reports, self.metric_results, self.journal_entries, self.evidence_events)):
            raise RetrospectiveFixtureError("The version-1 retained fixture must not contain invented retrospective observations.")
        if not isinstance(self.evaluation, RetrospectiveFixtureEvaluation) or set(self.evaluation.missing_input_ids) != {value.input_id for value in missing}:
            raise RetrospectiveFixtureError("The fixture evaluation must identify every absent retained input.")
        limitations = _text_tuple(self.limitations, "retrospective-fixture limitations", required=True)
        sources = _text_tuple(self.source_record_ids, "retrospective-fixture source identifiers", required=True)
        _unique(limitations, "retrospective-fixture limitations")
        _unique(sources, "retrospective-fixture source identifiers")
        evidence_sources = {identifier for value in (*facts, *missing) for identifier in value.source_record_ids}
        if not evidence_sources.issubset(sources) or not set(self.evaluation.source_record_ids).issubset(sources):
            raise RetrospectiveFixtureError("The fixture source inventory must cover every known and missing-input claim.")
        expected_change = ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 1.0, "cm H₂O"))
        if self.known_change != expected_change:
            raise RetrospectiveFixtureError("Fixture version 1 is restricted to the known PS Min 2-to-1 change.")
        if (self.fixture_id, self.fixture_version, self.record_version) != (PS_MIN_RETROSPECTIVE_FIXTURE_ID, PS_MIN_RETROSPECTIVE_FIXTURE_VERSION, PS_MIN_RETROSPECTIVE_FIXTURE_RECORD_VERSION):
            raise RetrospectiveFixtureError("The retrospective fixture identity or version is unsupported.")
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "known_facts", tuple(sorted(facts, key=lambda value: value.record_id)))
        object.__setattr__(self, "missing_inputs", tuple(sorted(missing, key=lambda value: value.input_id.value)))
        object.__setattr__(self, "limitations", tuple(sorted(limitations)))
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


def reconstruct_ps_min_experiment_fixture() -> PSMinRetrospectiveFixture:
    """Reconstruct only retained facts and identify everything still unavailable."""

    experiment = ExperimentRecord(
        record_id="experiment:ps-min-2-to-1:retrospective-v1",
        title="Retrospective PS Min 2 to 1",
        created_at_ms=0,
        created_by="fixture:pap-pilot",
        source_provenance_ids=_FIXTURE_PROVENANCE_IDS,
    )
    problem = _fixture_event(
        experiment,
        "event:ps-min-retrospective:problem",
        1,
        ExperimentEventType.PROBLEM_RECORDED,
        ProblemRecordedPayload("Evaluate the known retrospective fixed-EPAP ASV PS Min 2-to-1 change without assuming that the earlier informal interpretation was correct."),
        (_PLAN_PURPOSE_SOURCE, _PLAN_VERTICAL_SLICE_SOURCE),
    )
    hypothesis = _fixture_event(
        experiment,
        "event:ps-min-retrospective:hypothesis",
        2,
        ExperimentEventType.HYPOTHESIS_DRAFTED,
        HypothesisDraftedPayload(
            "Lowering PS Min may reduce independently calculated Mask Pressure above fixed EPAP without worsening independently calculated ventilation dispersion.",
            ("Confounding changes", "Incomplete or low-quality source evidence", "Normal night-to-night variation"),
        ),
        (_METRIC_DECISION_SOURCE, _PLAN_PURPOSE_SOURCE),
    )
    history = validate_experiment_history(experiment, (problem, hypothesis))
    known_change = ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 1.0, "cm H₂O"))
    facts = (
        RetrospectiveKnownFact("fact:ps-min-change", "The governing record identifies an informal fixed-EPAP ASV PS Min change from 2 to 1 cm H₂O.", (_PLAN_PURPOSE_SOURCE, _CLASSIFICATION_DECISION_SOURCE)),
        RetrospectiveKnownFact("fact:analysis-contract", f"The accepted deterministic analysis uses {METRIC_SET_ID} version {METRIC_SET_VERSION} and the version-1 outcome-classification rules.", (_METRIC_DECISION_SOURCE, _CLASSIFICATION_DECISION_SOURCE)),
        RetrospectiveKnownFact("fact:informal-impression", "The governing record describes the earlier interpretation only as subjectively meaningful; it supplies no attributable per-night structured journal observations.", (_PLAN_PURPOSE_SOURCE, _JOURNAL_DECISION_SOURCE)),
    )
    missing = _missing_inputs()
    reasons = tuple(f"{value.input_id.value}_missing" for value in missing) + ("outcome_classification_not_issued",)
    evaluation_sources = tuple(sorted({experiment.record_id, *(value.record_id for value in history), *(value.record_id for value in facts), *(identifier for value in (*facts, *missing) for identifier in value.source_record_ids)}))
    identity = repr((experiment, history, known_change, facts, missing, reasons, evaluation_sources))
    evaluation = RetrospectiveFixtureEvaluation(
        record_id=f"retrospective-fixture-evaluation:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        status=RetrospectiveFixtureEvaluationStatus.NOT_EVALUABLE_WITHOUT_FABRICATION,
        reason_codes=reasons,
        missing_input_ids=tuple(value.input_id for value in missing),
        source_record_ids=evaluation_sources,
    )
    sources = tuple(sorted({*evaluation_sources, _STATUS_BLOCKER_SOURCE}))
    return PSMinRetrospectiveFixture(
        record_id="retrospective-fixture:ps-min-2-to-1:v1",
        experiment=experiment,
        history=history,
        known_change=known_change,
        known_facts=facts,
        missing_inputs=missing,
        normalized_nights=(),
        structural_quality_reports=(),
        signal_quality_reports=(),
        allocation=None,
        metric_results=(),
        journal_entries=(),
        evidence_events=(),
        outcome_classification=None,
        evaluation=evaluation,
        limitations=(
            "This fixture is a reconstruction inventory, not a clinical conclusion or causal analysis.",
            "The fixed zero and low integer event timestamps are deterministic repository-fixture metadata sentinels, not therapy, report, or observation times.",
            "The earlier informal subjective impression is retained only as a planning fact and is not converted into a structured journal response.",
            "No private OSCAR identifier, date, session, signal, metric, journal response, confounder, or adverse-effect value is retained.",
            "An OutcomeClassificationResult must not be issued until every required source record can be linked without fabricated values.",
        ),
        source_record_ids=sources,
    )


def _missing_inputs() -> tuple[RetrospectiveMissingInput, ...]:
    common_sources = (_PLAN_VERTICAL_SLICE_SOURCE, _STATUS_BLOCKER_SOURCE)
    return (
        RetrospectiveMissingInput(RetrospectiveMissingInputId.ACCEPTED_PROPOSAL, "The retained record has no exact accepted proposal containing baseline dates, complete baseline settings, invalid-night criteria, and evidence links.", ("classification", "proposal acceptance replay"), common_sources),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.APPLIED_CHANGE_BOUNDARY, "The retained record has no user-confirmed application timestamp for the intended sustained change; an observed settings transition must not silently become a confirmation event.", ("baseline/intervention allocation", "classification"), common_sources),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.BASELINE_INTERVENTION_NIGHTS, "No private normalized-night cohort or explicit baseline/intervention date selection is retained in the repository.", ("allocation", "metric calculation", "classification"), common_sources),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.QUALITY_REPORTS, "No structural or signal-quality reports exist for an explicitly selected retrospective cohort.", ("allocation", "metric calculation"), (_PLAN_VERTICAL_SLICE_SOURCE,)),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.OBJECTIVE_METRIC_RESULTS, "Neither version-1 objective metric has been calculated for linked baseline and intervention nights.", ("classification",), (_METRIC_DECISION_SOURCE, _STATUS_BLOCKER_SOURCE)),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.STRUCTURED_JOURNAL_REPORTS, "No attributable per-night awakenings, sleep-quality, morning-energy, or daytime-tiredness entries are retained for the retrospective periods.", ("subjective aggregation", "classification"), (_JOURNAL_DECISION_SOURCE, _STATUS_BLOCKER_SOURCE)),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.CONFOUNDER_ADVERSE_EFFECT_EVIDENCE, "No linked per-night confounder or adverse-effect records are retained; their absence cannot be interpreted as none reported.", ("confounder assessment", "adverse-effect precedence", "classification"), (_JOURNAL_DECISION_SOURCE, _CLASSIFICATION_DECISION_SOURCE)),
        RetrospectiveMissingInput(RetrospectiveMissingInputId.REPRESENTATIVE_INTERVALS, "No baseline or intervention waveform interval has been selected and linked to retained source records.", ("accepted proposal", "later evidence report"), (_PLAN_VERTICAL_SLICE_SOURCE,)),
    )


def _fixture_event(experiment: ExperimentRecord, record_id: str, sequence_number: int, event_type: ExperimentEventType, payload: ProblemRecordedPayload | HypothesisDraftedPayload, supporting_sources: tuple[str, ...]) -> ExperimentEvent:
    return ExperimentEvent(
        record_id=record_id,
        experiment_record_id=experiment.record_id,
        sequence_number=sequence_number,
        event_type=event_type,
        recorded_at_ms=sequence_number,
        recorded_by="fixture:pap-pilot",
        payload=payload,
        source_class=SourceClass.COMPANION_DERIVED,
        source_record_ids=(experiment.record_id, *supporting_sources),
        source_provenance_ids=_FIXTURE_PROVENANCE_IDS,
    )


def _typed_tuple(values: object, value_type: type, label: str, *, required: bool = False) -> tuple:
    if type(values) is not tuple or any(not isinstance(value, value_type) for value in values) or (required and not values):
        raise RetrospectiveFixtureError(f"The {label} must be an immutable{' nonempty' if required else ''} {value_type.__name__} tuple.")
    return values


def _text_tuple(values: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values) or (required and not values):
        raise RetrospectiveFixtureError(f"The {label} must be an immutable{' nonempty' if required else ''} text tuple.")
    return values


def _unique(values: tuple, label: str) -> None:
    if len(set(values)) != len(values):
        raise RetrospectiveFixtureError(f"The {label} must be unique.")


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RetrospectiveFixtureError(f"The {label} must be nonempty text.")
