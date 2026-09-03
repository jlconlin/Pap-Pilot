"""Deterministic construction of append-only boundary corrections and notes."""

from pap_pilot.engine.experiments.model import ExperimentEvent, ExperimentEventType, ExperimentModelError, NoteRecordedPayload, SettingChangeConfirmedPayload
from pap_pilot.engine.experiments.storage import ReplayedExperiment
from pap_pilot.engine.model import SourceClass


def build_boundary_correction_events(
    replayed: ReplayedExperiment,
    *,
    corrected_event_id: str,
    applied_at_ms: int,
    note: str,
    recorded_at_ms: int,
    correction_event_id: str,
    note_event_id: str,
    recorded_by: str = "user:local",
) -> tuple[ExperimentEvent, ExperimentEvent]:
    """Build one boundary correction and its linked note without editing prior events."""

    if not isinstance(replayed, ReplayedExperiment):
        raise ExperimentModelError("A boundary correction requires a replayed experiment.")
    if type(corrected_event_id) is not str or not corrected_event_id.strip():
        raise ExperimentModelError("A boundary correction requires an event identifier.")
    current = replayed.latest_event(ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED)
    if current is None:
        raise ExperimentModelError("No confirmed applied-change boundary is available to correct.")
    if current.record_id != corrected_event_id:
        raise ExperimentModelError("A boundary correction must reference the current effective boundary event.")
    if type(applied_at_ms) is not int:
        raise ExperimentModelError("The corrected application timestamp must be an integer.")
    if applied_at_ms == current.payload.applied_at_ms:
        raise ExperimentModelError("The corrected application timestamp must differ from the current boundary.")
    if type(recorded_at_ms) is not int:
        raise ExperimentModelError("The correction recording timestamp must be an integer.")
    if type(note) is not str or not note.strip():
        raise ExperimentModelError("A boundary correction requires a nonempty note.")
    if any(type(value) is not str or not value.strip() for value in (correction_event_id, note_event_id, recorded_by)):
        raise ExperimentModelError("Correction event identifiers and actor must be nonempty text.")
    experiment_id = replayed.experiment.record_id
    provenance = ("provenance:user:local",)
    correction = ExperimentEvent(
        record_id=correction_event_id,
        experiment_record_id=experiment_id,
        sequence_number=len(replayed.history) + 1,
        event_type=ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED,
        recorded_at_ms=recorded_at_ms,
        recorded_by=recorded_by,
        payload=SettingChangeConfirmedPayload(current.payload.accepted_event_id, current.payload.applied_change, applied_at_ms),
        source_class=SourceClass.USER_REPORTED,
        source_record_ids=(experiment_id, current.record_id),
        source_provenance_ids=provenance,
        correction_of_event_id=current.record_id,
    )
    note_event = ExperimentEvent(
        record_id=note_event_id,
        experiment_record_id=experiment_id,
        sequence_number=len(replayed.history) + 2,
        event_type=ExperimentEventType.NOTE_RECORDED,
        recorded_at_ms=recorded_at_ms,
        recorded_by=recorded_by,
        payload=NoteRecordedPayload(note.strip(), correction.record_id),
        source_class=SourceClass.USER_REPORTED,
        source_record_ids=(experiment_id, correction.record_id),
        source_provenance_ids=provenance,
    )
    return correction, note_event
