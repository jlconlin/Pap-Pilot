"""Persist exact historical user evidence for one retrospective cohort."""

from dataclasses import dataclass
import hashlib
from typing import Final

from pap_pilot.engine.experiments.journal import (
    ConfounderReportStatus,
    RetrospectiveEvidenceStatus,
    RetrospectiveNightEvidence,
    RetrospectiveObservation,
    SleepJournalEntry,
)
from pap_pilot.engine.experiments.model import (
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentModelError,
    ExperimentProposedPayload,
    ObservationRecordedPayload,
    SettingChangeConfirmedPayload,
    SleepJournalEntryRecordedPayload,
)
from pap_pilot.engine.experiments.retrospective_protocol import (
    RetrospectiveCohortEvidence,
)
from pap_pilot.engine.experiments.storage import ExperimentStore, ReplayedExperiment
from pap_pilot.engine.model import SourceClass


RETROSPECTIVE_USER_EVIDENCE_INTAKE_VERSION: Final = 1
_EVIDENCE_EVENT_TYPES: Final = frozenset(
    {
        ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED,
        ExperimentEventType.CONFOUNDER_RECORDED,
        ExperimentEventType.ADVERSE_EFFECT_RECORDED,
    }
)


class RetrospectiveEvidenceError(ExperimentModelError):
    """Raised when historical user evidence is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class RetrospectiveNightEvidenceInput:
    """Exact user-supplied historical evidence state for one cohort night."""

    night_record_id: str
    journal_status: RetrospectiveEvidenceStatus
    journal_entry: SleepJournalEntry | None
    confounder_status: RetrospectiveEvidenceStatus
    confounders: tuple[RetrospectiveObservation, ...]
    adverse_effect_status: RetrospectiveEvidenceStatus
    adverse_effects: tuple[RetrospectiveObservation, ...]
    recorded_at_ms: int
    recorded_by: str
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    intake_version: int = RETROSPECTIVE_USER_EVIDENCE_INTAKE_VERSION

    def __post_init__(self) -> None:
        _text(self.night_record_id, "retrospective evidence night identifier")
        for value in (
            self.journal_status,
            self.confounder_status,
            self.adverse_effect_status,
        ):
            if not isinstance(value, RetrospectiveEvidenceStatus):
                raise RetrospectiveEvidenceError(
                    "Retrospective evidence input requires supported explicit statuses."
                )
        if self.journal_status is RetrospectiveEvidenceStatus.NONE_REPORTED:
            raise RetrospectiveEvidenceError(
                "A historical journal is either unavailable, not reported, or reported."
            )
        if self.journal_status is RetrospectiveEvidenceStatus.REPORTED:
            if not isinstance(self.journal_entry, SleepJournalEntry):
                raise RetrospectiveEvidenceError(
                    "Reported historical journal evidence requires its exact entry."
                )
            if self.journal_entry.night_record_id != self.night_record_id:
                raise RetrospectiveEvidenceError(
                    "A historical journal entry must belong to its selected cohort night."
                )
        elif self.journal_entry is not None:
            raise RetrospectiveEvidenceError(
                "Unavailable or not-reported journal evidence cannot carry an entry."
            )
        confounders = _observations(self.confounders, "historical confounders")
        adverse_effects = _observations(
            self.adverse_effects,
            "historical adverse effects",
        )
        if self.adverse_effect_status is RetrospectiveEvidenceStatus.REPORTED:
            if not adverse_effects:
                raise RetrospectiveEvidenceError(
                    "Reported historical adverse-effect evidence requires an exact observation."
                )
        elif adverse_effects:
            raise RetrospectiveEvidenceError(
                "Unreported historical adverse-effect evidence cannot carry observations."
            )
        if type(self.recorded_at_ms) is not int:
            raise RetrospectiveEvidenceError(
                "The retrospective evidence recording timestamp must be an integer."
            )
        _text(self.recorded_by, "retrospective evidence reporter")
        source_ids = _text_tuple(
            self.source_record_ids,
            "retrospective evidence source identifiers",
        )
        provenance_ids = _text_tuple(
            self.source_provenance_ids,
            "retrospective evidence provenance identifiers",
        )
        if self.intake_version != RETROSPECTIVE_USER_EVIDENCE_INTAKE_VERSION:
            raise RetrospectiveEvidenceError(
                "The retrospective evidence intake version is unsupported."
            )
        object.__setattr__(self, "confounders", confounders)
        object.__setattr__(self, "adverse_effects", adverse_effects)
        object.__setattr__(self, "source_record_ids", tuple(sorted(source_ids)))
        object.__setattr__(
            self,
            "source_provenance_ids",
            tuple(sorted(provenance_ids)),
        )


@dataclass(frozen=True, slots=True)
class RetrospectiveEvidenceBatch:
    """One validated atomic append for a complete selected cohort."""

    events: tuple[ExperimentEvent, ...]
    journal_entries: tuple[SleepJournalEntry, ...]
    night_evidence: tuple[RetrospectiveNightEvidence, ...]

    def __post_init__(self) -> None:
        if type(self.events) is not tuple or any(
            not isinstance(value, ExperimentEvent) for value in self.events
        ):
            raise RetrospectiveEvidenceError(
                "A retrospective evidence batch requires an immutable event tuple."
            )
        if type(self.journal_entries) is not tuple or any(
            not isinstance(value, SleepJournalEntry) for value in self.journal_entries
        ):
            raise RetrospectiveEvidenceError(
                "A retrospective evidence batch requires an immutable journal-entry tuple."
            )
        if type(self.night_evidence) is not tuple or not self.night_evidence or any(
            not isinstance(value, RetrospectiveNightEvidence)
            for value in self.night_evidence
        ):
            raise RetrospectiveEvidenceError(
                "A retrospective evidence batch requires nonempty immutable night evidence."
            )


def build_retrospective_user_evidence(
    replayed: ReplayedExperiment,
    cohort: RetrospectiveCohortEvidence,
    inputs: tuple[RetrospectiveNightEvidenceInput, ...],
) -> RetrospectiveEvidenceBatch:
    """Validate and build exact journal, observation, and status records."""

    if not isinstance(replayed, ReplayedExperiment):
        raise RetrospectiveEvidenceError(
            "Retrospective evidence construction requires a replayed experiment."
        )
    if not isinstance(cohort, RetrospectiveCohortEvidence):
        raise RetrospectiveEvidenceError(
            "Retrospective evidence construction requires selected cohort evidence."
        )
    if type(inputs) is not tuple or not inputs or any(
        not isinstance(value, RetrospectiveNightEvidenceInput) for value in inputs
    ):
        raise RetrospectiveEvidenceError(
            "Retrospective evidence input must be a nonempty immutable night tuple."
        )
    _validate_history(replayed, cohort)
    expected_night_ids = tuple(night.record_id for night in cohort.nights)
    supplied_ids = tuple(value.night_record_id for value in inputs)
    if len(set(supplied_ids)) != len(supplied_ids):
        raise RetrospectiveEvidenceError(
            "Retrospective evidence may supply each cohort night only once."
        )
    if set(supplied_ids) != set(expected_night_ids):
        raise RetrospectiveEvidenceError(
            "Retrospective evidence must explicitly cover every selected cohort night and no other night."
        )
    input_by_night = {value.night_record_id: value for value in inputs}

    experiment_id = replayed.experiment.record_id
    sequence = len(replayed.history) + 1
    events: list[ExperimentEvent] = []
    journals: list[SleepJournalEntry] = []
    evidence_records: list[RetrospectiveNightEvidence] = []
    used_journal_ids = {
        entry.record_id for entry in replayed.journal_history
    }

    for cohort_index, night in enumerate(cohort.nights):
        supplied = input_by_night[night.record_id]
        _validate_confounder_status(supplied)
        journal_event_id = None
        confounder_event_ids = []
        adverse_event_ids = []

        if supplied.journal_entry is not None:
            if supplied.journal_entry.record_id in used_journal_ids:
                raise RetrospectiveEvidenceError(
                    "A historical journal entry identifier cannot replace an existing record."
                )
            used_journal_ids.add(supplied.journal_entry.record_id)
            journal_payload = SleepJournalEntryRecordedPayload(
                supplied.journal_entry.record_id,
                night.record_id,
            )
            journal_event_id = _identifier(
                "journal",
                experiment_id,
                cohort.record_id,
                cohort_index,
                journal_payload,
                supplied.journal_entry,
                supplied.source_record_ids,
                supplied.source_provenance_ids,
            )
            journal_event = ExperimentEvent(
                record_id=journal_event_id,
                experiment_record_id=experiment_id,
                sequence_number=sequence,
                event_type=ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED,
                recorded_at_ms=supplied.journal_entry.reported_at_ms,
                recorded_by=supplied.journal_entry.reported_by,
                payload=journal_payload,
                source_class=SourceClass.USER_REPORTED,
                source_record_ids=tuple(
                    sorted(
                        {
                            experiment_id,
                            cohort.record_id,
                            night.record_id,
                            supplied.journal_entry.record_id,
                            *supplied.source_record_ids,
                        }
                    )
                ),
                source_provenance_ids=tuple(
                    sorted(
                        {
                            *supplied.source_provenance_ids,
                            *supplied.journal_entry.source_provenance_ids,
                        }
                    )
                ),
            )
            events.append(journal_event)
            journals.append(supplied.journal_entry)
            sequence += 1

        for event_kind, event_type, observations, target_ids in (
            (
                "confounder",
                ExperimentEventType.CONFOUNDER_RECORDED,
                supplied.confounders,
                confounder_event_ids,
            ),
            (
                "adverse-effect",
                ExperimentEventType.ADVERSE_EFFECT_RECORDED,
                supplied.adverse_effects,
                adverse_event_ids,
            ),
        ):
            for observation_index, observation in enumerate(observations):
                payload = ObservationRecordedPayload(
                    observation.description,
                    observation.observed_at_ms,
                    night.record_id,
                )
                event_id = _identifier(
                    event_kind,
                    experiment_id,
                    cohort.record_id,
                    cohort_index,
                    observation_index,
                    payload,
                    observation,
                    supplied.source_record_ids,
                    supplied.source_provenance_ids,
                )
                event = ExperimentEvent(
                    record_id=event_id,
                    experiment_record_id=experiment_id,
                    sequence_number=sequence,
                    event_type=event_type,
                    recorded_at_ms=observation.recorded_at_ms,
                    recorded_by=observation.recorded_by,
                    payload=payload,
                    source_class=SourceClass.USER_REPORTED,
                    source_record_ids=tuple(
                        sorted(
                            {
                                experiment_id,
                                cohort.record_id,
                                night.record_id,
                                *supplied.source_record_ids,
                                *observation.source_record_ids,
                            }
                        )
                    ),
                    source_provenance_ids=tuple(
                        sorted(
                            {
                                *supplied.source_provenance_ids,
                                *observation.source_provenance_ids,
                            }
                        )
                    ),
                )
                events.append(event)
                target_ids.append(event_id)
                sequence += 1

        linked_event_ids = (
            *((journal_event_id,) if journal_event_id is not None else ()),
            *confounder_event_ids,
            *adverse_event_ids,
        )
        all_provenance = {
            *supplied.source_provenance_ids,
            *(
                supplied.journal_entry.source_provenance_ids
                if supplied.journal_entry is not None
                else ()
            ),
            *(
                value
                for observation in (
                    *supplied.confounders,
                    *supplied.adverse_effects,
                )
                for value in observation.source_provenance_ids
            ),
        }
        all_sources = {
            experiment_id,
            cohort.record_id,
            night.record_id,
            *supplied.source_record_ids,
            *linked_event_ids,
            *(
                (supplied.journal_entry.record_id,)
                if supplied.journal_entry is not None
                else ()
            ),
            *(
                value
                for observation in (
                    *supplied.confounders,
                    *supplied.adverse_effects,
                )
                for value in observation.source_record_ids
            ),
        }
        record_id = _identifier(
            "night-evidence",
            experiment_id,
            cohort.record_id,
            cohort_index,
            supplied,
            linked_event_ids,
        )
        evidence_records.append(
            RetrospectiveNightEvidence(
                record_id=record_id,
                experiment_record_id=experiment_id,
                cohort_record_id=cohort.record_id,
                cohort_night_index=cohort_index,
                night_record_id=night.record_id,
                journal_status=supplied.journal_status,
                journal_entry=supplied.journal_entry,
                journal_event_id=journal_event_id,
                confounder_status=supplied.confounder_status,
                confounders=supplied.confounders,
                confounder_event_ids=tuple(confounder_event_ids),
                adverse_effect_status=supplied.adverse_effect_status,
                adverse_effects=supplied.adverse_effects,
                adverse_effect_event_ids=tuple(adverse_event_ids),
                recorded_at_ms=supplied.recorded_at_ms,
                recorded_by=supplied.recorded_by,
                source_record_ids=tuple(all_sources),
                source_provenance_ids=tuple(all_provenance),
            )
        )

    return RetrospectiveEvidenceBatch(
        tuple(events),
        tuple(journals),
        tuple(evidence_records),
    )


def record_retrospective_user_evidence(
    store: ExperimentStore,
    experiment_record_id: str,
    cohort: RetrospectiveCohortEvidence,
    inputs: tuple[RetrospectiveNightEvidenceInput, ...],
) -> ReplayedExperiment:
    """Atomically persist exact evidence and return its complete replay."""

    if not isinstance(store, ExperimentStore):
        raise RetrospectiveEvidenceError(
            "Retrospective evidence persistence requires an experiment store."
        )
    _text(experiment_record_id, "retrospective experiment identifier")
    replayed = store.replay(experiment_record_id)
    batch = build_retrospective_user_evidence(replayed, cohort, inputs)
    store.append_retrospective_evidence(
        batch.events,
        batch.journal_entries,
        batch.night_evidence,
    )
    return store.replay(experiment_record_id)


def _validate_history(
    replayed: ReplayedExperiment,
    cohort: RetrospectiveCohortEvidence,
) -> None:
    if replayed.effective_retrospective_evidence:
        raise RetrospectiveEvidenceError(
            "The experiment already contains retrospective user evidence."
        )
    if any(
        event.event_type in _EVIDENCE_EVENT_TYPES for event in replayed.history
    ):
        raise RetrospectiveEvidenceError(
            "The bounded retrospective intake cannot merge unmanifested user evidence."
        )
    proposals = replayed.events(ExperimentEventType.EXPERIMENT_PROPOSED)
    acceptances = replayed.events(ExperimentEventType.EXPERIMENT_ACCEPTED)
    confirmations = replayed.events(
        ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED
    )
    if len(proposals) != 1 or len(acceptances) != 1 or len(confirmations) != 1:
        raise RetrospectiveEvidenceError(
            "Retrospective user evidence requires one effective accepted protocol and confirmed boundary."
        )
    proposal, acceptance, confirmation = (
        proposals[0],
        acceptances[0],
        confirmations[0],
    )
    if not isinstance(proposal.payload, ExperimentProposedPayload):
        raise RetrospectiveEvidenceError("The effective proposal payload is invalid.")
    if not isinstance(acceptance.payload, ExperimentDecisionPayload):
        raise RetrospectiveEvidenceError("The effective acceptance payload is invalid.")
    if not isinstance(confirmation.payload, SettingChangeConfirmedPayload):
        raise RetrospectiveEvidenceError("The effective confirmation payload is invalid.")
    if (
        acceptance.payload.proposal_event_id != proposal.record_id
        or confirmation.payload.accepted_event_id != acceptance.record_id
        or confirmation.payload.applied_change != proposal.payload.proposal.proposed_change
    ):
        raise RetrospectiveEvidenceError(
            "The effective retrospective protocol chain is inconsistent."
        )
    if any(
        cohort.record_id not in event.source_record_ids
        for event in (proposal, acceptance, confirmation)
    ):
        raise RetrospectiveEvidenceError(
            "The effective retrospective protocol must link the selected cohort."
        )


def _validate_confounder_status(
    supplied: RetrospectiveNightEvidenceInput,
) -> None:
    entry = supplied.journal_entry
    has_standalone = bool(supplied.confounders)
    if has_standalone or (
        entry is not None
        and entry.confounder_status is ConfounderReportStatus.REPORTED
    ):
        expected = RetrospectiveEvidenceStatus.REPORTED
    elif entry is not None:
        expected = RetrospectiveEvidenceStatus(entry.confounder_status.value)
    else:
        expected = supplied.confounder_status
    if supplied.confounder_status is not expected:
        raise RetrospectiveEvidenceError(
            "The retrospective confounder status conflicts with the exact supplied journal and observations."
        )
    if supplied.confounder_status is RetrospectiveEvidenceStatus.REPORTED and not (
        has_standalone or (entry is not None and entry.confounders)
    ):
        raise RetrospectiveEvidenceError(
            "Reported retrospective confounder evidence requires exact supplied evidence."
        )
    if supplied.confounder_status is not RetrospectiveEvidenceStatus.REPORTED and (
        supplied.confounders
        or (entry is not None and entry.confounder_status is ConfounderReportStatus.REPORTED)
    ):
        raise RetrospectiveEvidenceError(
            "Unreported retrospective confounder evidence cannot carry observations."
        )


def _identifier(kind: str, *parts: object) -> str:
    identity = repr((RETROSPECTIVE_USER_EVIDENCE_INTAKE_VERSION, kind, parts))
    digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return f"{kind}:retrospective:{digest}"


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RetrospectiveEvidenceError(f"The {label} must be nonempty text.")


def _text_tuple(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values or any(
        type(value) is not str or not value.strip() for value in values
    ):
        raise RetrospectiveEvidenceError(
            f"The {label} must be a nonempty immutable text tuple."
        )
    if len(set(values)) != len(values):
        raise RetrospectiveEvidenceError(f"The {label} must be unique.")
    return values


def _observations(values: object, label: str) -> tuple[RetrospectiveObservation, ...]:
    if type(values) is not tuple or any(
        not isinstance(value, RetrospectiveObservation) for value in values
    ):
        raise RetrospectiveEvidenceError(
            f"The {label} must be an immutable observation tuple."
        )
    return values
