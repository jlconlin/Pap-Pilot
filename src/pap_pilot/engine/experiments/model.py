"""Immutable version-1 experiment and append-only event schemas."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import math
from typing import Final, TypeAlias

from pap_pilot.engine.model import SourceClass


EXPERIMENT_SCHEMA_ID: Final = "pap-pilot.experiment"
EXPERIMENT_SCHEMA_VERSION: Final = 1
EXPERIMENT_RECORD_VERSION: Final = 1
EXPERIMENT_EVENT_SCHEMA_ID: Final = "pap-pilot.experiment-event"
EXPERIMENT_EVENT_SCHEMA_VERSION: Final = 1
EXPERIMENT_EVENT_RECORD_VERSION: Final = 1

ExperimentScalar: TypeAlias = bool | int | float | str


class ExperimentModelError(ValueError):
    """Raised when an experiment record, event, or history is invalid."""


class ExperimentEventType(StrEnum):
    """Minimum append-only event vocabulary required by the governing plan."""

    PROBLEM_RECORDED = "problem_recorded"
    HYPOTHESIS_DRAFTED = "hypothesis_drafted"
    EXPERIMENT_PROPOSED = "experiment_proposed"
    EXPERIMENT_ACCEPTED = "experiment_accepted"
    EXPERIMENT_REJECTED = "experiment_rejected"
    EXPERIMENT_REVISED = "experiment_revised"
    SETTING_CHANGE_CONFIRMED_APPLIED = "setting_change_confirmed_applied"
    SLEEP_JOURNAL_ENTRY_RECORDED = "sleep_journal_entry_recorded"
    CONFOUNDER_RECORDED = "confounder_recorded"
    ADVERSE_EFFECT_RECORDED = "adverse_effect_recorded"
    EXPERIMENT_STOPPED = "experiment_stopped"
    EXPERIMENT_EXTENDED = "experiment_extended"
    EXPERIMENT_KEPT = "experiment_kept"
    EXPERIMENT_REVERTED = "experiment_reverted"
    EVALUATION_ISSUED = "evaluation_issued"
    EVALUATION_SUPERSEDED = "evaluation_superseded"


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """Stable identity for one experiment whose changing facts live in events."""

    record_id: str
    title: str
    created_at_ms: int
    created_by: str
    source_provenance_ids: tuple[str, ...]
    schema_id: str = EXPERIMENT_SCHEMA_ID
    schema_version: int = EXPERIMENT_SCHEMA_VERSION
    record_version: int = EXPERIMENT_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "experiment record identifier")
        _text(self.title, "experiment title")
        _integer(self.created_at_ms, "experiment creation timestamp")
        _text(self.created_by, "experiment creator")
        provenance_ids = _required_text_tuple(self.source_provenance_ids, "experiment source provenance identifiers")
        _unique(provenance_ids, "experiment source provenance identifiers")
        if self.schema_id != EXPERIMENT_SCHEMA_ID or type(self.schema_version) is not int or self.schema_version != EXPERIMENT_SCHEMA_VERSION or type(self.record_version) is not int or self.record_version != EXPERIMENT_RECORD_VERSION:
            raise ExperimentModelError("The experiment schema or record version is unsupported.")
        object.__setattr__(self, "source_provenance_ids", tuple(sorted(provenance_ids)))


@dataclass(frozen=True, slots=True)
class ExperimentSetting:
    """One exact setting value used by an experiment design or applied change."""

    name: str
    value: ExperimentScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        _text(self.name, "experiment setting name")
        _scalar(self.value, "experiment setting value")
        _optional_text(self.unit, "experiment setting unit")


@dataclass(frozen=True, slots=True)
class ExperimentSettingChange:
    """One proposed or confirmed single-variable setting change."""

    previous: ExperimentSetting
    proposed: ExperimentSetting

    def __post_init__(self) -> None:
        _instance(self.previous, ExperimentSetting, "previous experiment setting")
        _instance(self.proposed, ExperimentSetting, "proposed experiment setting")
        if self.previous.name != self.proposed.name or self.previous.unit != self.proposed.unit:
            raise ExperimentModelError("A setting change must retain one setting identity and unit.")
        if self.previous.value == self.proposed.value:
            raise ExperimentModelError("A setting change requires distinct previous and proposed values.")


@dataclass(frozen=True, slots=True)
class ExperimentEvidenceInterval:
    """One representative source interval linked to an experiment proposal."""

    night_record_id: str
    session_record_id: str
    start_time_ms: int | float
    end_time_ms: int | float
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.night_record_id, "evidence night identifier")
        _text(self.session_record_id, "evidence session identifier")
        start = _timestamp(self.start_time_ms, "evidence interval start")
        end = _timestamp(self.end_time_ms, "evidence interval end")
        if start >= end:
            raise ExperimentModelError("An experiment evidence interval must be positive and half-open.")
        source_ids = _required_text_tuple(self.source_record_ids, "evidence source record identifiers")
        _unique(source_ids, "evidence source record identifiers")
        if self.night_record_id not in source_ids or self.session_record_id not in source_ids:
            raise ExperimentModelError("Evidence sources must include the interval's night and session identifiers.")
        object.__setattr__(self, "start_time_ms", start)
        object.__setattr__(self, "end_time_ms", end)
        object.__setattr__(self, "source_record_ids", tuple(sorted(source_ids)))


@dataclass(frozen=True, slots=True)
class ExperimentProposal:
    """Complete structural design for one controlled experiment proposal."""

    problem_event_id: str
    hypothesis_event_id: str
    baseline_local_dates: tuple[str, ...]
    baseline_settings: tuple[ExperimentSetting, ...]
    proposed_change: ExperimentSettingChange
    settings_held_fixed: tuple[ExperimentSetting, ...]
    evidence_record_ids: tuple[str, ...]
    representative_intervals: tuple[ExperimentEvidenceInterval, ...]
    expected_objective_effects: tuple[str, ...]
    expected_subjective_effects: tuple[str, ...]
    minimum_valid_nights: int
    invalid_night_criteria: tuple[str, ...]
    possible_adverse_effects: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    revert_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.problem_event_id, "proposal problem-event identifier")
        _text(self.hypothesis_event_id, "proposal hypothesis-event identifier")
        dates = _required_text_tuple(self.baseline_local_dates, "baseline local dates")
        for value in dates:
            _iso_date(value, "baseline local date")
        _unique(dates, "baseline local dates")
        baseline = _settings(self.baseline_settings, "baseline settings", required=True)
        held_fixed = _settings(self.settings_held_fixed, "settings held fixed", required=True)
        _instance(self.proposed_change, ExperimentSettingChange, "proposed setting change")
        baseline_by_name = {setting.name: setting for setting in baseline}
        if baseline_by_name.get(self.proposed_change.previous.name) != self.proposed_change.previous:
            raise ExperimentModelError("Baseline settings must contain the exact pre-change setting value.")
        held_fixed_by_name = {setting.name: setting for setting in held_fixed}
        if self.proposed_change.previous.name in held_fixed_by_name:
            raise ExperimentModelError("The changed setting cannot also be held fixed.")
        if any(baseline_by_name.get(name) != setting for name, setting in held_fixed_by_name.items()):
            raise ExperimentModelError("Every held-fixed setting must match its baseline value.")
        evidence_ids = _required_text_tuple(self.evidence_record_ids, "proposal evidence record identifiers")
        _unique(evidence_ids, "proposal evidence record identifiers")
        intervals = _typed_tuple(self.representative_intervals, ExperimentEvidenceInterval, "representative evidence intervals", required=True)
        for interval in intervals:
            if any(identifier not in evidence_ids for identifier in interval.source_record_ids):
                raise ExperimentModelError("Representative interval sources must be included in proposal evidence identifiers.")
        collections = (
            (self.expected_objective_effects, "expected objective effects"),
            (self.expected_subjective_effects, "expected subjective effects"),
            (self.invalid_night_criteria, "invalid-night criteria"),
            (self.possible_adverse_effects, "possible adverse effects"),
            (self.stop_conditions, "stop conditions"),
            (self.revert_conditions, "revert conditions"),
        )
        normalized_collections = []
        for values, label in collections:
            normalized = _required_text_tuple(values, label)
            _unique(normalized, label)
            normalized_collections.append(tuple(sorted(normalized)))
        if type(self.minimum_valid_nights) is not int or self.minimum_valid_nights <= 0:
            raise ExperimentModelError("The minimum valid-night count must be a positive integer.")
        object.__setattr__(self, "baseline_local_dates", tuple(sorted(dates)))
        object.__setattr__(self, "baseline_settings", tuple(sorted(baseline, key=lambda value: value.name)))
        object.__setattr__(self, "settings_held_fixed", tuple(sorted(held_fixed, key=lambda value: value.name)))
        object.__setattr__(self, "evidence_record_ids", tuple(sorted(evidence_ids)))
        object.__setattr__(self, "representative_intervals", tuple(sorted(intervals, key=lambda value: (value.start_time_ms, value.session_record_id))))
        for field_name, normalized in zip(
            ("expected_objective_effects", "expected_subjective_effects", "invalid_night_criteria", "possible_adverse_effects", "stop_conditions", "revert_conditions"),
            normalized_collections,
        ):
            object.__setattr__(self, field_name, normalized)


@dataclass(frozen=True, slots=True)
class ProblemRecordedPayload:
    """The problem an experiment is intended to investigate."""

    problem: str

    def __post_init__(self) -> None:
        _text(self.problem, "recorded problem")


@dataclass(frozen=True, slots=True)
class HypothesisDraftedPayload:
    """A hypothesis plus alternative explanations that could fit the evidence."""

    hypothesis: str
    competing_explanations: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.hypothesis, "drafted hypothesis")
        alternatives = _required_text_tuple(self.competing_explanations, "competing explanations")
        _unique(alternatives, "competing explanations")
        object.__setattr__(self, "competing_explanations", tuple(sorted(alternatives)))


@dataclass(frozen=True, slots=True)
class ExperimentProposedPayload:
    """A fully specified structural experiment proposal."""

    proposal: ExperimentProposal

    def __post_init__(self) -> None:
        _instance(self.proposal, ExperimentProposal, "experiment proposal")


@dataclass(frozen=True, slots=True)
class ExperimentDecisionPayload:
    """A user decision about one proposal or revision."""

    proposal_event_id: str
    rationale: str

    def __post_init__(self) -> None:
        _text(self.proposal_event_id, "decided proposal-event identifier")
        _text(self.rationale, "experiment decision rationale")


@dataclass(frozen=True, slots=True)
class ExperimentRevisedPayload:
    """A revised proposal that preserves its predecessor by reference."""

    revises_proposal_event_id: str
    proposal: ExperimentProposal

    def __post_init__(self) -> None:
        _text(self.revises_proposal_event_id, "revised proposal-event identifier")
        _instance(self.proposal, ExperimentProposal, "revised experiment proposal")


@dataclass(frozen=True, slots=True)
class SettingChangeConfirmedPayload:
    """The setting change the user reports actually applying, and when."""

    accepted_event_id: str
    applied_change: ExperimentSettingChange
    applied_at_ms: int

    def __post_init__(self) -> None:
        _text(self.accepted_event_id, "accepted event identifier")
        _instance(self.applied_change, ExperimentSettingChange, "applied setting change")
        _integer(self.applied_at_ms, "setting application timestamp")


@dataclass(frozen=True, slots=True)
class SleepJournalEntryRecordedPayload:
    """A reference to journal content whose detailed schema is owned by S28."""

    journal_entry_record_id: str
    night_record_id: str

    def __post_init__(self) -> None:
        _text(self.journal_entry_record_id, "sleep-journal entry identifier")
        _text(self.night_record_id, "sleep-journal night identifier")


@dataclass(frozen=True, slots=True)
class ObservationRecordedPayload:
    """A confounder or adverse effect observed during an experiment."""

    description: str
    observed_at_ms: int
    night_record_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.description, "recorded observation")
        _integer(self.observed_at_ms, "observation timestamp")
        _optional_text(self.night_record_id, "observation night identifier")


@dataclass(frozen=True, slots=True)
class ExperimentActionPayload:
    """Reason and effective time for a stop, extension, keep, or revert action."""

    rationale: str
    effective_at_ms: int
    extension_end_local_date: str | None = None

    def __post_init__(self) -> None:
        _text(self.rationale, "experiment action rationale")
        _integer(self.effective_at_ms, "experiment action timestamp")
        if self.extension_end_local_date is not None:
            _iso_date(self.extension_end_local_date, "extension end local date")


@dataclass(frozen=True, slots=True)
class EvaluationIssuedPayload:
    """A reference to a deterministic evaluation defined by later sprints."""

    evaluation_record_id: str

    def __post_init__(self) -> None:
        _text(self.evaluation_record_id, "issued evaluation identifier")


@dataclass(frozen=True, slots=True)
class EvaluationSupersededPayload:
    """An additive link from an earlier evaluation event to its successor."""

    superseded_evaluation_event_id: str
    replacement_evaluation_record_id: str

    def __post_init__(self) -> None:
        _text(self.superseded_evaluation_event_id, "superseded evaluation-event identifier")
        _text(self.replacement_evaluation_record_id, "replacement evaluation identifier")


ExperimentEventPayload: TypeAlias = (
    ProblemRecordedPayload
    | HypothesisDraftedPayload
    | ExperimentProposedPayload
    | ExperimentDecisionPayload
    | ExperimentRevisedPayload
    | SettingChangeConfirmedPayload
    | SleepJournalEntryRecordedPayload
    | ObservationRecordedPayload
    | ExperimentActionPayload
    | EvaluationIssuedPayload
    | EvaluationSupersededPayload
)

_PAYLOAD_BY_EVENT_TYPE: Final = {
    ExperimentEventType.PROBLEM_RECORDED: ProblemRecordedPayload,
    ExperimentEventType.HYPOTHESIS_DRAFTED: HypothesisDraftedPayload,
    ExperimentEventType.EXPERIMENT_PROPOSED: ExperimentProposedPayload,
    ExperimentEventType.EXPERIMENT_ACCEPTED: ExperimentDecisionPayload,
    ExperimentEventType.EXPERIMENT_REJECTED: ExperimentDecisionPayload,
    ExperimentEventType.EXPERIMENT_REVISED: ExperimentRevisedPayload,
    ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED: SettingChangeConfirmedPayload,
    ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED: SleepJournalEntryRecordedPayload,
    ExperimentEventType.CONFOUNDER_RECORDED: ObservationRecordedPayload,
    ExperimentEventType.ADVERSE_EFFECT_RECORDED: ObservationRecordedPayload,
    ExperimentEventType.EXPERIMENT_STOPPED: ExperimentActionPayload,
    ExperimentEventType.EXPERIMENT_EXTENDED: ExperimentActionPayload,
    ExperimentEventType.EXPERIMENT_KEPT: ExperimentActionPayload,
    ExperimentEventType.EXPERIMENT_REVERTED: ExperimentActionPayload,
    ExperimentEventType.EVALUATION_ISSUED: EvaluationIssuedPayload,
    ExperimentEventType.EVALUATION_SUPERSEDED: EvaluationSupersededPayload,
}


@dataclass(frozen=True, slots=True)
class ExperimentEvent:
    """One immutable event envelope suitable for an append-only ledger."""

    record_id: str
    experiment_record_id: str
    sequence_number: int
    event_type: ExperimentEventType
    recorded_at_ms: int
    recorded_by: str
    payload: ExperimentEventPayload
    source_class: SourceClass
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    correction_of_event_id: str | None = None
    schema_id: str = EXPERIMENT_EVENT_SCHEMA_ID
    schema_version: int = EXPERIMENT_EVENT_SCHEMA_VERSION
    record_version: int = EXPERIMENT_EVENT_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "experiment event identifier")
        _text(self.experiment_record_id, "event experiment identifier")
        if type(self.sequence_number) is not int or self.sequence_number <= 0:
            raise ExperimentModelError("An experiment event sequence number must be a positive integer.")
        _enum(self.event_type, ExperimentEventType, "experiment event type")
        _integer(self.recorded_at_ms, "experiment event timestamp")
        _text(self.recorded_by, "experiment event actor")
        expected_payload = _PAYLOAD_BY_EVENT_TYPE[self.event_type]
        if not isinstance(self.payload, expected_payload):
            raise ExperimentModelError("The experiment event payload does not match its event type.")
        _enum(self.source_class, SourceClass, "experiment event source class")
        if self.source_class not in {SourceClass.USER_REPORTED, SourceClass.COMPANION_DERIVED, SourceClass.AI_GENERATED}:
            raise ExperimentModelError("An experiment event must be user-reported, companion-derived, or AI-generated.")
        source_ids = _required_text_tuple(self.source_record_ids, "experiment event source record identifiers")
        provenance_ids = _required_text_tuple(self.source_provenance_ids, "experiment event source provenance identifiers")
        _unique(source_ids, "experiment event source record identifiers")
        _unique(provenance_ids, "experiment event source provenance identifiers")
        if self.experiment_record_id not in source_ids:
            raise ExperimentModelError("Experiment event sources must include the experiment record identifier.")
        _optional_text(self.correction_of_event_id, "corrected experiment-event identifier")
        if self.correction_of_event_id == self.record_id:
            raise ExperimentModelError("An experiment event cannot correct itself.")
        if self.schema_id != EXPERIMENT_EVENT_SCHEMA_ID or type(self.schema_version) is not int or self.schema_version != EXPERIMENT_EVENT_SCHEMA_VERSION or type(self.record_version) is not int or self.record_version != EXPERIMENT_EVENT_RECORD_VERSION:
            raise ExperimentModelError("The experiment-event schema or record version is unsupported.")
        if self.event_type is ExperimentEventType.EXPERIMENT_EXTENDED and self.payload.extension_end_local_date is None:
            raise ExperimentModelError("An experiment extension requires its new end date.")
        if self.event_type in {ExperimentEventType.EXPERIMENT_STOPPED, ExperimentEventType.EXPERIMENT_KEPT, ExperimentEventType.EXPERIMENT_REVERTED} and self.payload.extension_end_local_date is not None:
            raise ExperimentModelError("Only an experiment extension can carry an extension end date.")
        object.__setattr__(self, "source_record_ids", tuple(sorted(source_ids)))
        object.__setattr__(self, "source_provenance_ids", tuple(sorted(provenance_ids)))


def validate_experiment_history(experiment: ExperimentRecord, events: tuple[ExperimentEvent, ...]) -> tuple[ExperimentEvent, ...]:
    """Validate one complete history without replaying experiment state."""

    _instance(experiment, ExperimentRecord, "experiment record")
    history = _typed_tuple(events, ExperimentEvent, "experiment event history")
    identifiers: dict[str, ExperimentEvent] = {}
    for expected_sequence, event in enumerate(history, start=1):
        if event.experiment_record_id != experiment.record_id:
            raise ExperimentModelError("Every event in a history must belong to its experiment.")
        if event.sequence_number != expected_sequence:
            raise ExperimentModelError("Experiment events must be appended with contiguous sequence numbers.")
        if event.record_id in identifiers:
            raise ExperimentModelError("An existing experiment event cannot be replaced; append a correction event instead.")
        if event.correction_of_event_id is not None:
            corrected = identifiers.get(event.correction_of_event_id)
            if corrected is None:
                raise ExperimentModelError("A correction must reference an earlier event in the same history.")
            if corrected.event_type is not event.event_type:
                raise ExperimentModelError("A correction must retain the corrected event type.")
        if event.event_type is ExperimentEventType.EXPERIMENT_PROPOSED:
            _earlier_event(identifiers, event.payload.proposal.problem_event_id, {ExperimentEventType.PROBLEM_RECORDED}, "A proposal's problem reference")
            _earlier_event(identifiers, event.payload.proposal.hypothesis_event_id, {ExperimentEventType.HYPOTHESIS_DRAFTED}, "A proposal's hypothesis reference")
        elif event.event_type in {ExperimentEventType.EXPERIMENT_ACCEPTED, ExperimentEventType.EXPERIMENT_REJECTED}:
            _earlier_event(identifiers, event.payload.proposal_event_id, {ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentEventType.EXPERIMENT_REVISED}, "An experiment decision's proposal reference")
        elif event.event_type is ExperimentEventType.EXPERIMENT_REVISED:
            _earlier_event(identifiers, event.payload.revises_proposal_event_id, {ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentEventType.EXPERIMENT_REVISED}, "An experiment revision's proposal reference")
        elif event.event_type is ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED:
            _earlier_event(identifiers, event.payload.accepted_event_id, {ExperimentEventType.EXPERIMENT_ACCEPTED}, "A setting confirmation's acceptance reference")
        elif event.event_type is ExperimentEventType.EVALUATION_SUPERSEDED:
            _earlier_event(identifiers, event.payload.superseded_evaluation_event_id, {ExperimentEventType.EVALUATION_ISSUED}, "An evaluation supersession reference")
        identifiers[event.record_id] = event
    return history


def append_experiment_event(experiment: ExperimentRecord, history: tuple[ExperimentEvent, ...], event: ExperimentEvent) -> tuple[ExperimentEvent, ...]:
    """Return a validated history with one new event appended."""

    _instance(event, ExperimentEvent, "appended experiment event")
    existing = validate_experiment_history(experiment, history)
    return validate_experiment_history(experiment, (*existing, event))


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ExperimentModelError(f"The {label} must be nonempty text.")


def _optional_text(value: object, label: str) -> None:
    if value is not None:
        _text(value, label)


def _integer(value: object, label: str) -> None:
    if type(value) is not int:
        raise ExperimentModelError(f"The {label} must be an integer.")


def _timestamp(value: object, label: str) -> int | float:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ExperimentModelError(f"The {label} must be a finite millisecond number.")


def _scalar(value: object, label: str) -> None:
    if type(value) in (bool, int, str) or type(value) is float and math.isfinite(value):
        return
    raise ExperimentModelError(f"The {label} must be a finite JSON scalar.")


def _iso_date(value: object, label: str) -> None:
    _text(value, label)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ExperimentModelError(f"The {label} must be an ISO 8601 calendar date.") from error
    if parsed.isoformat() != value:
        raise ExperimentModelError(f"The {label} must use canonical ISO 8601 form.")


def _enum(value: object, expected: type[StrEnum], label: str) -> None:
    if not isinstance(value, expected):
        raise ExperimentModelError(f"The {label} has an unsupported value.")


def _instance(value: object, expected: type[object], label: str) -> None:
    if not isinstance(value, expected):
        raise ExperimentModelError(f"The {label} has the wrong record type.")


def _required_text_tuple(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values or any(type(value) is not str or not value.strip() for value in values):
        raise ExperimentModelError(f"The {label} must be a nonempty tuple of nonempty text values.")
    return values


def _typed_tuple(values: object, expected: type[object], label: str, *, required: bool = False) -> tuple[object, ...]:
    if type(values) is not tuple or required and not values or any(not isinstance(value, expected) for value in values):
        qualification = "nonempty " if required else ""
        raise ExperimentModelError(f"The {label} must be a {qualification}tuple of {expected.__name__} records.")
    return values


def _settings(values: object, label: str, *, required: bool) -> tuple[ExperimentSetting, ...]:
    settings = _typed_tuple(values, ExperimentSetting, label, required=required)
    _unique(tuple(value.name for value in settings), f"{label} names")
    return settings


def _earlier_event(events: dict[str, ExperimentEvent], record_id: str, allowed_types: set[ExperimentEventType], label: str) -> None:
    target = events.get(record_id)
    if target is None or target.event_type not in allowed_types:
        raise ExperimentModelError(f"{label} must identify an earlier compatible event.")


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ExperimentModelError(f"The {label} must be unique.")
