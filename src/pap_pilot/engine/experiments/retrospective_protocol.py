"""Persist one explicitly accepted retrospective protocol and boundary."""

from dataclasses import dataclass
import hashlib
from typing import Final

from pap_pilot.engine.experiments.model import (
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentModelError,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentSetting,
    ExperimentSettingChange,
    SettingChangeConfirmedPayload,
)
from pap_pilot.engine.experiments.storage import (
    ExperimentStore,
    ReplayedExperiment,
)
from pap_pilot.engine.model import (
    NightRecord,
    ProvenanceRecord,
    SessionRecord,
    SourceClass,
)


RETROSPECTIVE_PROTOCOL_RECORD_VERSION: Final = 1
_REQUIRED_SETTING_NAMES: Final = frozenset(
    {
        "therapy_mode_code",
        "loader_mode_code",
        "epap",
        "ps_min",
        "ps_max",
        "max_ipap",
    }
)
_EXPECTED_CHANGE: Final = ExperimentSettingChange(
    previous=ExperimentSetting("ps_min", 2.0, "cm H₂O"),
    proposed=ExperimentSetting("ps_min", 1.0, "cm H₂O"),
)
_PROTOCOL_EVENT_TYPES: Final = frozenset(
    {
        ExperimentEventType.EXPERIMENT_PROPOSED,
        ExperimentEventType.EXPERIMENT_ACCEPTED,
        ExperimentEventType.EXPERIMENT_REJECTED,
        ExperimentEventType.EXPERIMENT_REVISED,
        ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED,
    }
)


class RetrospectiveProtocolError(ExperimentModelError):
    """Raised when supplied retrospective protocol facts are inconsistent."""


@dataclass(frozen=True, slots=True)
class RetrospectiveCohortEvidence:
    """Source-independent link to one explicitly selected normalized cohort."""

    record_id: str
    nights: tuple[NightRecord, ...]
    source_record_ids: tuple[str, ...]
    record_version: int = RETROSPECTIVE_PROTOCOL_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "retrospective cohort identifier")
        if type(self.nights) is not tuple or not self.nights or any(
            not isinstance(night, NightRecord) for night in self.nights
        ):
            raise RetrospectiveProtocolError(
                "Retrospective cohort evidence requires a nonempty immutable night tuple."
            )
        if len({night.record_id for night in self.nights}) != len(self.nights):
            raise RetrospectiveProtocolError(
                "Retrospective cohort night identifiers must be unique."
            )
        sessions = tuple(session for night in self.nights for session in night.sessions)
        if len({session.record_id for session in sessions}) != len(sessions):
            raise RetrospectiveProtocolError(
                "Retrospective cohort session identifiers must be unique."
            )
        sources = _text_tuple(
            self.source_record_ids,
            "retrospective cohort source identifiers",
        )
        if self.record_version != RETROSPECTIVE_PROTOCOL_RECORD_VERSION:
            raise RetrospectiveProtocolError(
                "The retrospective cohort-evidence record version is unsupported."
            )
        object.__setattr__(
            self,
            "nights",
            tuple(sorted(self.nights, key=lambda night: (night.local_date, night.record_id))),
        )
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


@dataclass(frozen=True, slots=True)
class RetrospectiveProtocolInput:
    """Exact user decisions required to append the retrospective protocol."""

    proposal: ExperimentProposal
    user_accepted: bool
    acceptance_rationale: str
    confirmed_change: ExperimentSettingChange
    boundary_user_confirmed: bool
    applied_at_ms: int
    proposal_recorded_at_ms: int
    accepted_at_ms: int
    confirmed_at_ms: int
    recorded_by: str
    user_source_record_ids: tuple[str, ...]
    user_provenance_ids: tuple[str, ...]
    record_version: int = RETROSPECTIVE_PROTOCOL_RECORD_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, ExperimentProposal):
            raise RetrospectiveProtocolError(
                "Retrospective protocol input requires an exact experiment proposal."
            )
        if self.user_accepted is not True:
            raise RetrospectiveProtocolError(
                "The retrospective proposal must be explicitly accepted by the user."
            )
        _text(self.acceptance_rationale, "retrospective acceptance rationale")
        if not isinstance(self.confirmed_change, ExperimentSettingChange):
            raise RetrospectiveProtocolError(
                "Retrospective protocol input requires an explicitly confirmed setting change."
            )
        if self.boundary_user_confirmed is not True:
            raise RetrospectiveProtocolError(
                "The retrospective applied-change boundary must be explicitly user-confirmed."
            )
        for value, label in (
            (self.applied_at_ms, "applied-change timestamp"),
            (self.proposal_recorded_at_ms, "proposal recording timestamp"),
            (self.accepted_at_ms, "acceptance timestamp"),
            (self.confirmed_at_ms, "confirmation timestamp"),
        ):
            _integer(value, label)
        if not self.proposal_recorded_at_ms <= self.accepted_at_ms <= self.confirmed_at_ms:
            raise RetrospectiveProtocolError(
                "Proposal, acceptance, and confirmation recording timestamps must be chronological."
            )
        if self.applied_at_ms > self.confirmed_at_ms:
            raise RetrospectiveProtocolError(
                "A retrospective boundary cannot be confirmed before the reported application time."
            )
        _text(self.recorded_by, "retrospective protocol actor")
        user_sources = _text_tuple(
            self.user_source_record_ids,
            "user confirmation source identifiers",
        )
        user_provenance = _text_tuple(
            self.user_provenance_ids,
            "user confirmation provenance identifiers",
        )
        if self.record_version != RETROSPECTIVE_PROTOCOL_RECORD_VERSION:
            raise RetrospectiveProtocolError(
                "The retrospective protocol-input record version is unsupported."
            )
        object.__setattr__(self, "user_source_record_ids", tuple(sorted(user_sources)))
        object.__setattr__(self, "user_provenance_ids", tuple(sorted(user_provenance)))


def build_retrospective_protocol_events(
    replayed: ReplayedExperiment,
    cohort: RetrospectiveCohortEvidence,
    protocol: RetrospectiveProtocolInput,
) -> tuple[ExperimentEvent, ExperimentEvent, ExperimentEvent]:
    """Validate explicit input and build proposal, acceptance, and confirmation events."""

    if not isinstance(replayed, ReplayedExperiment):
        raise RetrospectiveProtocolError(
            "Retrospective protocol construction requires a replayed experiment."
        )
    if not isinstance(cohort, RetrospectiveCohortEvidence):
        raise RetrospectiveProtocolError(
            "Retrospective protocol construction requires selected cohort evidence."
        )
    if not isinstance(protocol, RetrospectiveProtocolInput):
        raise RetrospectiveProtocolError(
            "Retrospective protocol construction requires explicit user input."
        )
    _validate_history(replayed, protocol.proposal)
    cohort_provenance_ids = _validate_cohort(cohort, protocol)

    experiment_id = replayed.experiment.record_id
    sequence = len(replayed.history) + 1
    proposal_payload = ExperimentProposedPayload(protocol.proposal)
    proposal_id = _event_id(
        "proposal",
        experiment_id,
        cohort.record_id,
        proposal_payload,
        protocol.proposal_recorded_at_ms,
        cohort_provenance_ids,
    )
    proposal = ExperimentEvent(
        record_id=proposal_id,
        experiment_record_id=experiment_id,
        sequence_number=sequence,
        event_type=ExperimentEventType.EXPERIMENT_PROPOSED,
        recorded_at_ms=protocol.proposal_recorded_at_ms,
        recorded_by="pap-pilot:retrospective-protocol",
        payload=proposal_payload,
        source_class=SourceClass.COMPANION_DERIVED,
        source_record_ids=tuple(
            sorted(
                {
                    experiment_id,
                    cohort.record_id,
                    protocol.proposal.problem_event_id,
                    protocol.proposal.hypothesis_event_id,
                    *protocol.proposal.evidence_record_ids,
                }
            )
        ),
        source_provenance_ids=cohort_provenance_ids,
    )

    acceptance_payload = ExperimentDecisionPayload(
        proposal.record_id,
        protocol.acceptance_rationale,
    )
    acceptance_id = _event_id(
        "acceptance",
        experiment_id,
        cohort.record_id,
        acceptance_payload,
        protocol.accepted_at_ms,
        protocol.recorded_by,
        protocol.user_source_record_ids,
        protocol.user_provenance_ids,
    )
    acceptance = ExperimentEvent(
        record_id=acceptance_id,
        experiment_record_id=experiment_id,
        sequence_number=sequence + 1,
        event_type=ExperimentEventType.EXPERIMENT_ACCEPTED,
        recorded_at_ms=protocol.accepted_at_ms,
        recorded_by=protocol.recorded_by,
        payload=acceptance_payload,
        source_class=SourceClass.USER_REPORTED,
        source_record_ids=tuple(
            sorted(
                {
                    experiment_id,
                    cohort.record_id,
                    proposal.record_id,
                    *protocol.user_source_record_ids,
                }
            )
        ),
        source_provenance_ids=protocol.user_provenance_ids,
    )

    confirmation_payload = SettingChangeConfirmedPayload(
        acceptance.record_id,
        protocol.confirmed_change,
        protocol.applied_at_ms,
    )
    confirmation_id = _event_id(
        "boundary",
        experiment_id,
        cohort.record_id,
        confirmation_payload,
        protocol.confirmed_at_ms,
        protocol.recorded_by,
        protocol.user_source_record_ids,
        protocol.user_provenance_ids,
    )
    confirmation = ExperimentEvent(
        record_id=confirmation_id,
        experiment_record_id=experiment_id,
        sequence_number=sequence + 2,
        event_type=ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED,
        recorded_at_ms=protocol.confirmed_at_ms,
        recorded_by=protocol.recorded_by,
        payload=confirmation_payload,
        source_class=SourceClass.USER_REPORTED,
        source_record_ids=tuple(
            sorted(
                {
                    experiment_id,
                    cohort.record_id,
                    acceptance.record_id,
                    *protocol.user_source_record_ids,
                }
            )
        ),
        source_provenance_ids=protocol.user_provenance_ids,
    )
    return proposal, acceptance, confirmation


def record_retrospective_protocol(
    store: ExperimentStore,
    experiment_record_id: str,
    cohort: RetrospectiveCohortEvidence,
    protocol: RetrospectiveProtocolInput,
) -> ReplayedExperiment:
    """Atomically append the validated protocol and return its effective replay."""

    if not isinstance(store, ExperimentStore):
        raise RetrospectiveProtocolError(
            "Retrospective protocol persistence requires an experiment store."
        )
    _text(experiment_record_id, "retrospective experiment identifier")
    replayed = store.replay(experiment_record_id)
    events = build_retrospective_protocol_events(replayed, cohort, protocol)
    store.append_events(events)
    return store.replay(experiment_record_id)


def _validate_history(
    replayed: ReplayedExperiment,
    proposal: ExperimentProposal,
) -> None:
    if any(event.event_type in _PROTOCOL_EVENT_TYPES for event in replayed.history):
        raise RetrospectiveProtocolError(
            "The experiment history already contains a retrospective protocol decision."
        )
    problems = replayed.events(ExperimentEventType.PROBLEM_RECORDED)
    hypotheses = replayed.events(ExperimentEventType.HYPOTHESIS_DRAFTED)
    if len(problems) != 1 or len(hypotheses) != 1:
        raise RetrospectiveProtocolError(
            "The retrospective protocol requires exactly one effective problem and hypothesis."
        )
    if (
        proposal.problem_event_id != problems[0].record_id
        or proposal.hypothesis_event_id != hypotheses[0].record_id
    ):
        raise RetrospectiveProtocolError(
            "The retrospective proposal must reference the effective problem and hypothesis."
        )


def _validate_cohort(
    cohort: RetrospectiveCohortEvidence,
    protocol: RetrospectiveProtocolInput,
) -> tuple[str, ...]:
    proposal = protocol.proposal
    if proposal.proposed_change != _EXPECTED_CHANGE:
        raise RetrospectiveProtocolError(
            "The retrospective protocol is restricted to the PS Min 2-to-1 change."
        )
    if protocol.confirmed_change != proposal.proposed_change:
        raise RetrospectiveProtocolError(
            "The user-confirmed setting change must exactly match the accepted proposal."
        )
    baseline_by_name = {setting.name: setting for setting in proposal.baseline_settings}
    if set(baseline_by_name) != _REQUIRED_SETTING_NAMES:
        raise RetrospectiveProtocolError(
            "The retrospective proposal requires the complete fixed-EPAP ASV setting context."
        )
    held_fixed_by_name = {
        setting.name: setting for setting in proposal.settings_held_fixed
    }
    if set(held_fixed_by_name) != _REQUIRED_SETTING_NAMES - {"ps_min"}:
        raise RetrospectiveProtocolError(
            "The retrospective proposal must hold every setting except PS Min fixed."
        )
    if any(
        baseline_by_name[name] != setting
        for name, setting in held_fixed_by_name.items()
    ):
        raise RetrospectiveProtocolError(
            "Every held-fixed retrospective setting must match its baseline value."
        )
    if cohort.record_id not in proposal.evidence_record_ids:
        raise RetrospectiveProtocolError(
            "The retrospective proposal must link the selected cohort as evidence."
        )

    night_by_date = {night.local_date: night for night in cohort.nights}
    if len(night_by_date) != len(cohort.nights):
        raise RetrospectiveProtocolError(
            "The selected cohort cannot contain duplicate normalized local dates."
        )
    if any(value not in night_by_date for value in proposal.baseline_local_dates):
        raise RetrospectiveProtocolError(
            "Every accepted baseline date must resolve to the selected cohort."
        )
    if any(
        night.record_id not in proposal.evidence_record_ids
        for value, night in night_by_date.items()
        if value in proposal.baseline_local_dates
    ):
        raise RetrospectiveProtocolError(
            "Every accepted baseline night must be linked as proposal evidence."
        )

    sessions = tuple(session for night in cohort.nights for session in night.sessions)
    before_count = 0
    after_count = 0
    for session in sessions:
        settings = {
            setting.name: ExperimentSetting(setting.name, setting.value, setting.unit)
            for setting in session.settings
        }
        if set(settings) != _REQUIRED_SETTING_NAMES:
            raise RetrospectiveProtocolError(
                "Every selected session requires the complete fixed-EPAP ASV setting context."
            )
        for held in proposal.settings_held_fixed:
            if settings.get(held.name) != held:
                raise RetrospectiveProtocolError(
                    "A selected session conflicts with a setting the accepted proposal holds fixed."
                )
        if session.end_time_ms <= protocol.applied_at_ms:
            before_count += 1
            expected_change_setting = proposal.proposed_change.previous
        elif session.start_time_ms >= protocol.applied_at_ms:
            after_count += 1
            expected_change_setting = proposal.proposed_change.proposed
        else:
            raise RetrospectiveProtocolError(
                "The user-confirmed boundary cannot fall inside a selected therapy session."
            )
        if settings.get("ps_min") != expected_change_setting:
            raise RetrospectiveProtocolError(
                "Selected session settings conflict with the user-confirmed PS Min boundary."
            )
    if before_count == 0 or after_count == 0:
        raise RetrospectiveProtocolError(
            "The selected cohort must contain sessions on both sides of the confirmed boundary."
        )

    for local_date in proposal.baseline_local_dates:
        night = night_by_date[local_date]
        if any(session.end_time_ms > protocol.applied_at_ms for session in night.sessions):
            raise RetrospectiveProtocolError(
                "An accepted baseline night must end no later than the confirmed boundary."
            )
        for session in night.sessions:
            settings = {
                setting.name: ExperimentSetting(setting.name, setting.value, setting.unit)
                for setting in session.settings
            }
            if settings != baseline_by_name:
                raise RetrospectiveProtocolError(
                    "Accepted baseline settings must exactly match every session on each baseline date."
                )

    inventory, provenance_ids, session_by_id = _cohort_inventory(cohort)
    for interval in proposal.representative_intervals:
        session_entry = session_by_id.get(interval.session_record_id)
        if session_entry is None or session_entry[0] != interval.night_record_id:
            raise RetrospectiveProtocolError(
                "Every proposal interval must resolve to its selected cohort night and session."
            )
        session = session_entry[1]
        if (
            interval.start_time_ms < session.start_time_ms
            or interval.end_time_ms > session.end_time_ms
        ):
            raise RetrospectiveProtocolError(
                "Every proposal interval must remain within its selected session."
            )
        if any(source not in inventory for source in interval.source_record_ids):
            raise RetrospectiveProtocolError(
                "Every proposal interval source must resolve within the selected cohort."
            )
    return provenance_ids


def _cohort_inventory(
    cohort: RetrospectiveCohortEvidence,
) -> tuple[set[str], tuple[str, ...], dict[str, tuple[str, SessionRecord]]]:
    inventory = {cohort.record_id, *cohort.source_record_ids}
    provenance_ids = set()
    session_by_id = {}
    for night in cohort.nights:
        inventory.add(night.record_id)
        _add_provenance(inventory, provenance_ids, night.provenance)
        for session in night.sessions:
            inventory.add(session.record_id)
            session_by_id[session.record_id] = (night.record_id, session)
            _add_provenance(inventory, provenance_ids, session.provenance)
            for record in (*session.settings, *session.events, *session.signals):
                inventory.add(record.record_id)
                _add_provenance(inventory, provenance_ids, record.provenance)
            for signal in session.signals:
                for segment in signal.segments:
                    inventory.add(segment.record_id)
                    _add_provenance(inventory, provenance_ids, segment.provenance)
    return inventory, tuple(sorted(provenance_ids)), session_by_id


def _add_provenance(
    inventory: set[str],
    provenance_ids: set[str],
    provenance: ProvenanceRecord,
) -> None:
    inventory.add(provenance.record_id)
    provenance_ids.add(provenance.record_id)
    inventory.update(
        f"{reference.source_record_type}:{reference.source_record_id}"
        for reference in provenance.source_references
    )


def _event_id(
    event_kind: str,
    experiment_record_id: str,
    cohort_record_id: str,
    *identity_parts: object,
) -> str:
    identity = repr(
        (
            RETROSPECTIVE_PROTOCOL_RECORD_VERSION,
            event_kind,
            experiment_record_id,
            cohort_record_id,
            identity_parts,
        )
    )
    return f"event:retrospective-{event_kind}:{hashlib.sha256(identity.encode()).hexdigest()[:20]}"


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise RetrospectiveProtocolError(f"The {label} must be nonempty text.")


def _text_tuple(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values or any(
        type(value) is not str or not value.strip() for value in values
    ):
        raise RetrospectiveProtocolError(
            f"The {label} must be a nonempty immutable text tuple."
        )
    if len(set(values)) != len(values):
        raise RetrospectiveProtocolError(f"The {label} must be unique.")
    return values


def _integer(value: object, label: str) -> None:
    if type(value) is not int:
        raise RetrospectiveProtocolError(f"The {label} must be an integer.")
