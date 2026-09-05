"""Append-only prospective experiment lifecycle validation and replay."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pap_pilot.engine.experiments.model import (
    ExperimentEvent,
    ExperimentEventType,
    ExperimentModelError,
    ExperimentRecord,
    append_experiment_event,
    validate_experiment_history,
)


PROSPECTIVE_LIFECYCLE_ENGINE_VERSION: Final = "pap-pilot.prospective-lifecycle-v1"


class ProspectiveLifecycleStatus(StrEnum):
    EMPTY = "empty"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    APPLIED = "applied"
    EXTENDED = "extended"
    STOPPED = "stopped"
    KEPT = "kept"
    REVERTED = "reverted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ProspectiveLifecycleError(ValueError):
    """Raised when an event is not valid for the current lifecycle state."""


@dataclass(frozen=True, slots=True)
class ProspectiveLifecycleState:
    """Correction-resolved state projection over an immutable experiment ledger."""

    status: ProspectiveLifecycleStatus
    proposal_event_id: str | None = None
    decision_event_id: str | None = None
    applied_event_id: str | None = None
    terminal_event_id: str | None = None
    effective_events: tuple[ExperimentEvent, ...] = ()


def replay_prospective_lifecycle(experiment: ExperimentRecord, events: tuple[ExperimentEvent, ...]) -> ProspectiveLifecycleState:
    """Replay effective lifecycle events, preserving corrected originals in the ledger."""

    history = validate_experiment_history(experiment, events)
    corrected = {event.correction_of_event_id for event in history if event.correction_of_event_id is not None}
    effective = tuple(event for event in history if event.record_id not in corrected)
    state = ProspectiveLifecycleState(ProspectiveLifecycleStatus.EMPTY, effective_events=effective)
    for event in effective:
        state = _apply(state, event)
    return state


def append_prospective_lifecycle_event(experiment: ExperimentRecord, history: tuple[ExperimentEvent, ...], event: ExperimentEvent) -> tuple[ExperimentEvent, ...]:
    """Validate and append one lifecycle event without replacing prior history."""

    candidate = append_experiment_event(experiment, history, event)
    replay_prospective_lifecycle(experiment, candidate)
    return candidate


def _apply(state: ProspectiveLifecycleState, event: ExperimentEvent) -> ProspectiveLifecycleState:
    kind = event.event_type
    status = state.status
    if kind is ExperimentEventType.EXPERIMENT_PROPOSED or kind is ExperimentEventType.EXPERIMENT_REVISED:
        if status not in {ProspectiveLifecycleStatus.EMPTY, ProspectiveLifecycleStatus.PROPOSED, ProspectiveLifecycleStatus.REJECTED}:
            raise ProspectiveLifecycleError("A proposal or revision is not valid after the experiment has advanced.")
        proposal_id = event.record_id
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.PROPOSED, proposal_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.EXPERIMENT_ACCEPTED:
        if status is not ProspectiveLifecycleStatus.PROPOSED or event.payload.proposal_event_id != state.proposal_event_id:
            raise ProspectiveLifecycleError("Only the current proposal can be accepted.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.ACCEPTED, state.proposal_event_id, event.record_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.EXPERIMENT_REJECTED:
        if status is not ProspectiveLifecycleStatus.PROPOSED or event.payload.proposal_event_id != state.proposal_event_id:
            raise ProspectiveLifecycleError("Only the current proposal can be rejected.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.REJECTED, state.proposal_event_id, event.record_id, terminal_event_id=event.record_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED:
        if status is not ProspectiveLifecycleStatus.ACCEPTED:
            raise ProspectiveLifecycleError("A setting application requires an accepted proposal.")
        if event.payload.accepted_event_id != state.decision_event_id:
            raise ProspectiveLifecycleError("The setting application must reference the current acceptance.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.APPLIED, state.proposal_event_id, state.decision_event_id, event.record_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.EXPERIMENT_EXTENDED:
        if status not in {ProspectiveLifecycleStatus.APPLIED, ProspectiveLifecycleStatus.EXTENDED}:
            raise ProspectiveLifecycleError("Only an applied experiment can be extended.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.EXTENDED, state.proposal_event_id, state.decision_event_id, state.applied_event_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.EXPERIMENT_STOPPED:
        if status not in {ProspectiveLifecycleStatus.APPLIED, ProspectiveLifecycleStatus.EXTENDED}:
            raise ProspectiveLifecycleError("Only an active experiment can be stopped.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.STOPPED, state.proposal_event_id, state.decision_event_id, state.applied_event_id, event.record_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.EXPERIMENT_KEPT:
        if status not in {ProspectiveLifecycleStatus.APPLIED, ProspectiveLifecycleStatus.EXTENDED}:
            raise ProspectiveLifecycleError("Only an active experiment can be kept.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.KEPT, state.proposal_event_id, state.decision_event_id, state.applied_event_id, event.record_id, effective_events=state.effective_events)
    if kind is ExperimentEventType.EXPERIMENT_REVERTED:
        if status not in {ProspectiveLifecycleStatus.APPLIED, ProspectiveLifecycleStatus.EXTENDED, ProspectiveLifecycleStatus.STOPPED, ProspectiveLifecycleStatus.KEPT}:
            raise ProspectiveLifecycleError("Only an applied, stopped, or kept experiment can be reverted.")
        return ProspectiveLifecycleState(ProspectiveLifecycleStatus.REVERTED, state.proposal_event_id, state.decision_event_id, state.applied_event_id, event.record_id, effective_events=state.effective_events)
    return state
