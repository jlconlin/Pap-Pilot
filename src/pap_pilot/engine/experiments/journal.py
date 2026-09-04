"""Immutable version-1 sleep-journal records for experiment evidence."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pap_pilot.engine.model import SourceClass


SLEEP_JOURNAL_SCHEMA_ID: Final = "pap-pilot.sleep-journal"
SLEEP_JOURNAL_SCHEMA_VERSION: Final = 1
SLEEP_JOURNAL_RECORD_VERSION: Final = 1
JOURNAL_RATING_MINIMUM: Final = 1
JOURNAL_RATING_MAXIMUM: Final = 5
RETROSPECTIVE_USER_EVIDENCE_SCHEMA_ID: Final = "pap-pilot.retrospective-user-evidence"
RETROSPECTIVE_USER_EVIDENCE_SCHEMA_VERSION: Final = 1
RETROSPECTIVE_USER_EVIDENCE_RECORD_VERSION: Final = 1


class SleepJournalModelError(ValueError):
    """Raised when a journal entry violates its versioned schema."""


class ConfounderReportStatus(StrEnum):
    """Whether confounders were answered and, if so, observed."""

    NOT_REPORTED = "not_reported"
    NONE_REPORTED = "none_reported"
    REPORTED = "reported"


class ConfounderKind(StrEnum):
    """Small initial vocabulary needed by the retrospective experiment."""

    TRAVEL = "travel"
    ILLNESS = "illness"
    ALCOHOL = "alcohol"
    MEDICATION_CHANGE = "medication_change"
    UNUSUAL_SLEEP_SCHEDULE = "unusual_sleep_schedule"
    MASK_OR_EQUIPMENT_CHANGE = "mask_or_equipment_change"
    STRESS = "stress"
    OTHER = "other"


class RetrospectiveEvidenceStatus(StrEnum):
    """Whether one historical evidence domain was available and answered."""

    UNAVAILABLE = "unavailable"
    NOT_REPORTED = "not_reported"
    NONE_REPORTED = "none_reported"
    REPORTED = "reported"


@dataclass(frozen=True, slots=True)
class SleepJournalConfounder:
    """One user-reported confounder with optional untouched detail."""

    kind: ConfounderKind
    details: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ConfounderKind):
            raise SleepJournalModelError("A journal confounder has an unsupported kind.")
        _optional_original_text(self.details, "confounder details")
        if self.kind is ConfounderKind.OTHER and self.details is None:
            raise SleepJournalModelError("An other confounder requires original details.")


@dataclass(frozen=True, slots=True)
class SleepJournalEntry:
    """One attributable morning report linked to exactly one therapy night."""

    record_id: str
    night_record_id: str
    reported_at_ms: int
    reported_by: str
    awakenings_count: int | None
    sleep_quality: int | None
    morning_energy: int | None
    daytime_tiredness: int | None
    confounder_status: ConfounderReportStatus
    confounders: tuple[SleepJournalConfounder, ...]
    original_note: str | None
    source_provenance_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.USER_REPORTED
    schema_id: str = SLEEP_JOURNAL_SCHEMA_ID
    schema_version: int = SLEEP_JOURNAL_SCHEMA_VERSION
    record_version: int = SLEEP_JOURNAL_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "sleep-journal entry identifier")
        _text(self.night_record_id, "sleep-journal night identifier")
        if type(self.reported_at_ms) is not int:
            raise SleepJournalModelError("The journal report timestamp must be an integer.")
        _text(self.reported_by, "sleep-journal reporter")
        if self.awakenings_count is not None and (type(self.awakenings_count) is not int or self.awakenings_count < 0):
            raise SleepJournalModelError("Estimated awakenings must be a nonnegative integer or null.")
        for value, label in ((self.sleep_quality, "sleep quality"), (self.morning_energy, "morning energy"), (self.daytime_tiredness, "daytime tiredness")):
            if value is not None and (type(value) is not int or not JOURNAL_RATING_MINIMUM <= value <= JOURNAL_RATING_MAXIMUM):
                raise SleepJournalModelError(f"The {label} rating must be an integer from 1 through 5 or null.")
        if not isinstance(self.confounder_status, ConfounderReportStatus):
            raise SleepJournalModelError("The journal confounder-report status is unsupported.")
        if type(self.confounders) is not tuple or any(not isinstance(value, SleepJournalConfounder) for value in self.confounders):
            raise SleepJournalModelError("Journal confounders must be an immutable confounder tuple.")
        if len({value.kind for value in self.confounders}) != len(self.confounders):
            raise SleepJournalModelError("Journal confounder kinds must be unique within an entry.")
        if (self.confounder_status is ConfounderReportStatus.REPORTED) != bool(self.confounders):
            raise SleepJournalModelError("Reported confounders require entries, while none or not-reported states require none.")
        _optional_original_text(self.original_note, "original journal note")
        provenance = _text_tuple(self.source_provenance_ids, "journal source provenance identifiers", required=True)
        if len(set(provenance)) != len(provenance):
            raise SleepJournalModelError("Journal source provenance identifiers must be unique.")
        if self.source_class is not SourceClass.USER_REPORTED:
            raise SleepJournalModelError("Sleep-journal entries must remain user-reported.")
        if (self.schema_id, self.schema_version, self.record_version) != (SLEEP_JOURNAL_SCHEMA_ID, SLEEP_JOURNAL_SCHEMA_VERSION, SLEEP_JOURNAL_RECORD_VERSION):
            raise SleepJournalModelError("The sleep-journal schema or record version is unsupported.")
        responses = (self.awakenings_count, self.sleep_quality, self.morning_energy, self.daytime_tiredness)
        if all(value is None for value in responses) and self.confounder_status is ConfounderReportStatus.NOT_REPORTED and self.original_note is None:
            raise SleepJournalModelError("A journal entry must contain at least one reported response, confounder answer, or original note.")
        object.__setattr__(self, "confounders", tuple(sorted(self.confounders, key=lambda value: value.kind.value)))
        object.__setattr__(self, "source_provenance_ids", tuple(sorted(provenance)))


@dataclass(frozen=True, slots=True)
class RetrospectiveObservation:
    """One exact historical confounder or adverse-effect statement."""

    description: str
    observed_at_ms: int
    recorded_at_ms: int
    recorded_by: str
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.USER_REPORTED

    def __post_init__(self) -> None:
        _original_text(self.description, "retrospective observation description")
        if type(self.observed_at_ms) is not int or type(self.recorded_at_ms) is not int:
            raise SleepJournalModelError(
                "Retrospective observation timestamps must be integers."
            )
        _text(self.recorded_by, "retrospective observation reporter")
        source_ids = _text_tuple(
            self.source_record_ids,
            "retrospective observation source identifiers",
            required=True,
        )
        provenance_ids = _text_tuple(
            self.source_provenance_ids,
            "retrospective observation provenance identifiers",
            required=True,
        )
        if len(set(source_ids)) != len(source_ids) or len(set(provenance_ids)) != len(
            provenance_ids
        ):
            raise SleepJournalModelError(
                "Retrospective observation source and provenance identifiers must be unique."
            )
        if self.source_class is not SourceClass.USER_REPORTED:
            raise SleepJournalModelError(
                "Retrospective observations must remain user-reported."
            )
        object.__setattr__(self, "source_record_ids", tuple(sorted(source_ids)))
        object.__setattr__(
            self,
            "source_provenance_ids",
            tuple(sorted(provenance_ids)),
        )


@dataclass(frozen=True, slots=True)
class RetrospectiveNightEvidence:
    """One persisted, explicitly statused historical evidence manifest."""

    record_id: str
    experiment_record_id: str
    cohort_record_id: str
    cohort_night_index: int
    night_record_id: str
    journal_status: RetrospectiveEvidenceStatus
    journal_entry: SleepJournalEntry | None
    journal_event_id: str | None
    confounder_status: RetrospectiveEvidenceStatus
    confounders: tuple[RetrospectiveObservation, ...]
    confounder_event_ids: tuple[str, ...]
    adverse_effect_status: RetrospectiveEvidenceStatus
    adverse_effects: tuple[RetrospectiveObservation, ...]
    adverse_effect_event_ids: tuple[str, ...]
    recorded_at_ms: int
    recorded_by: str
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.USER_REPORTED
    schema_id: str = RETROSPECTIVE_USER_EVIDENCE_SCHEMA_ID
    schema_version: int = RETROSPECTIVE_USER_EVIDENCE_SCHEMA_VERSION
    record_version: int = RETROSPECTIVE_USER_EVIDENCE_RECORD_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.record_id, "retrospective evidence identifier"),
            (self.experiment_record_id, "retrospective evidence experiment identifier"),
            (self.cohort_record_id, "retrospective evidence cohort identifier"),
            (self.night_record_id, "retrospective evidence night identifier"),
            (self.recorded_by, "retrospective evidence reporter"),
        ):
            _text(value, label)
        if type(self.cohort_night_index) is not int or self.cohort_night_index < 0:
            raise SleepJournalModelError(
                "The retrospective cohort-night index must be a nonnegative integer."
            )
        if type(self.recorded_at_ms) is not int:
            raise SleepJournalModelError(
                "The retrospective evidence timestamp must be an integer."
            )
        for value in (
            self.journal_status,
            self.confounder_status,
            self.adverse_effect_status,
        ):
            if not isinstance(value, RetrospectiveEvidenceStatus):
                raise SleepJournalModelError(
                    "Retrospective evidence requires supported explicit statuses."
                )
        if self.journal_status is RetrospectiveEvidenceStatus.NONE_REPORTED:
            raise SleepJournalModelError(
                "A journal domain cannot use none-reported; it is either unavailable, not reported, or reported."
            )
        journal_present = self.journal_entry is not None or self.journal_event_id is not None
        if self.journal_status is RetrospectiveEvidenceStatus.REPORTED:
            if not isinstance(self.journal_entry, SleepJournalEntry):
                raise SleepJournalModelError(
                    "Reported retrospective journal evidence requires its exact entry."
                )
            _text(self.journal_event_id, "retrospective journal event identifier")
            if self.journal_entry.night_record_id != self.night_record_id:
                raise SleepJournalModelError(
                    "The retrospective journal entry must belong to its evidence night."
                )
        elif journal_present:
            raise SleepJournalModelError(
                "Unavailable or not-reported journal evidence cannot carry an entry or event."
            )
        confounders = _typed_tuple(
            self.confounders,
            RetrospectiveObservation,
            "retrospective confounder observations",
        )
        adverse_effects = _typed_tuple(
            self.adverse_effects,
            RetrospectiveObservation,
            "retrospective adverse-effect observations",
        )
        confounder_event_ids = _text_tuple(
            self.confounder_event_ids,
            "retrospective confounder event identifiers",
        )
        adverse_effect_event_ids = _text_tuple(
            self.adverse_effect_event_ids,
            "retrospective adverse-effect event identifiers",
        )
        _statused_observations(
            self.confounder_status,
            confounders,
            confounder_event_ids,
            "confounder",
            alternate_reported=bool(
                self.journal_entry is not None
                and self.journal_entry.confounders
            ),
        )
        _statused_observations(
            self.adverse_effect_status,
            adverse_effects,
            adverse_effect_event_ids,
            "adverse-effect",
        )
        all_event_ids = (
            *((self.journal_event_id,) if self.journal_event_id is not None else ()),
            *confounder_event_ids,
            *adverse_effect_event_ids,
        )
        if len(set(all_event_ids)) != len(all_event_ids):
            raise SleepJournalModelError(
                "Retrospective evidence event identifiers must be unique across domains."
            )
        source_ids = _text_tuple(
            self.source_record_ids,
            "retrospective evidence source identifiers",
            required=True,
        )
        provenance_ids = _text_tuple(
            self.source_provenance_ids,
            "retrospective evidence provenance identifiers",
            required=True,
        )
        if len(set(source_ids)) != len(source_ids) or len(set(provenance_ids)) != len(
            provenance_ids
        ):
            raise SleepJournalModelError(
                "Retrospective evidence source and provenance identifiers must be unique."
            )
        required_sources = {
            self.experiment_record_id,
            self.cohort_record_id,
            self.night_record_id,
            *all_event_ids,
        }
        if self.journal_entry is not None:
            required_sources.add(self.journal_entry.record_id)
        if not required_sources.issubset(source_ids):
            raise SleepJournalModelError(
                "Retrospective evidence sources must cover its experiment, cohort, night, and linked records."
            )
        if self.source_class is not SourceClass.USER_REPORTED:
            raise SleepJournalModelError(
                "Retrospective evidence manifests must remain user-reported."
            )
        if (
            self.schema_id,
            self.schema_version,
            self.record_version,
        ) != (
            RETROSPECTIVE_USER_EVIDENCE_SCHEMA_ID,
            RETROSPECTIVE_USER_EVIDENCE_SCHEMA_VERSION,
            RETROSPECTIVE_USER_EVIDENCE_RECORD_VERSION,
        ):
            raise SleepJournalModelError(
                "The retrospective user-evidence schema or record version is unsupported."
            )
        object.__setattr__(self, "confounders", confounders)
        object.__setattr__(self, "confounder_event_ids", confounder_event_ids)
        object.__setattr__(self, "adverse_effects", adverse_effects)
        object.__setattr__(self, "adverse_effect_event_ids", adverse_effect_event_ids)
        object.__setattr__(self, "source_record_ids", tuple(sorted(source_ids)))
        object.__setattr__(
            self,
            "source_provenance_ids",
            tuple(sorted(provenance_ids)),
        )


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise SleepJournalModelError(f"The {label} must be nonempty text.")


def _optional_original_text(value: object, label: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise SleepJournalModelError(f"The {label} must be nonempty text or null.")


def _original_text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise SleepJournalModelError(f"The {label} must be nonempty text.")


def _text_tuple(values: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values) or (required and not values):
        raise SleepJournalModelError(f"The {label} must be an immutable{' nonempty' if required else ''} text tuple.")
    return values


def _typed_tuple(values: object, expected_type: type, label: str) -> tuple:
    if type(values) is not tuple or any(
        not isinstance(value, expected_type) for value in values
    ):
        raise SleepJournalModelError(f"The {label} must be an immutable typed tuple.")
    return values


def _statused_observations(
    status: RetrospectiveEvidenceStatus,
    observations: tuple[RetrospectiveObservation, ...],
    event_ids: tuple[str, ...],
    label: str,
    *,
    alternate_reported: bool = False,
) -> None:
    if len(observations) != len(event_ids):
        raise SleepJournalModelError(
            f"Retrospective {label} observations and event identifiers must correspond exactly."
        )
    if status is RetrospectiveEvidenceStatus.REPORTED:
        if not observations and not alternate_reported:
            raise SleepJournalModelError(
                f"Reported retrospective {label} evidence requires at least one exact observation."
            )
    elif observations or event_ids or alternate_reported:
        raise SleepJournalModelError(
            f"Unreported retrospective {label} evidence cannot carry observations or events."
        )
