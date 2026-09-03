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


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise SleepJournalModelError(f"The {label} must be nonempty text.")


def _optional_original_text(value: object, label: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise SleepJournalModelError(f"The {label} must be nonempty text or null.")


def _text_tuple(values: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values) or (required and not values):
        raise SleepJournalModelError(f"The {label} must be an immutable{' nonempty' if required else ''} text tuple.")
    return values
