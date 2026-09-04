"""Compose a selected OSCAR cohort with the deterministic retrospective engine."""

from pap_pilot.adapter import (
    OscarCorrectionEvidenceState,
    OscarNormalizedCohort,
)
from pap_pilot.engine.experiments.retrospective_evaluation import (
    RetrospectiveEvaluationBundle,
    RetrospectiveEvaluationError,
    RetrospectiveSessionClockEvidence,
    evaluate_retrospective_experiment,
)
from pap_pilot.engine.experiments.retrospective_protocol import (
    RetrospectiveCohortEvidence,
)
from pap_pilot.engine.experiments.storage import ReplayedExperiment
from pap_pilot.engine.model import SessionRecord
from pap_pilot.engine.quality import (
    ClockCorrectionEvidence,
    ClockCorrectionEvidenceState,
)


def evaluate_selected_oscar_retrospective_experiment(
    cohort: OscarNormalizedCohort,
    replayed: ReplayedExperiment,
) -> RetrospectiveEvaluationBundle:
    """Map exact S37A correction evidence and run the complete S37D pipeline."""

    if not isinstance(cohort, OscarNormalizedCohort):
        raise RetrospectiveEvaluationError(
            "Selected retrospective evaluation requires an OSCAR normalized cohort."
        )
    if not isinstance(replayed, ReplayedExperiment):
        raise RetrospectiveEvaluationError(
            "Selected retrospective evaluation requires a replayed experiment."
        )
    generic_cohort = RetrospectiveCohortEvidence(
        record_id=cohort.record_id,
        nights=cohort.nights,
        source_record_ids=cohort.source_record_ids,
    )
    time_by_database_id = {
        value.session_database_id: value
        for value in cohort.session_time_evidence
    }
    clocks = []
    for night in cohort.nights:
        for session in night.sessions:
            source_session_id = _source_session_database_id(session)
            time_evidence = time_by_database_id[source_session_id]
            active_types = tuple(
                sorted(
                    {
                        value.correction_type.value
                        for value in time_evidence.observed_corrections
                        if value.is_active
                    }
                )
            )
            if time_evidence.state is OscarCorrectionEvidenceState.CONFIRMED_NONE:
                evidence = ClockCorrectionEvidence(
                    state=ClockCorrectionEvidenceState.CONFIRMED_NONE,
                    source_record_ids=time_evidence.source_record_ids,
                )
            elif time_evidence.state is OscarCorrectionEvidenceState.SUPPORTED_CONSTANT:
                evidence = ClockCorrectionEvidence(
                    state=ClockCorrectionEvidenceState.SUPPORTED_CONSTANT,
                    source_record_ids=time_evidence.source_record_ids,
                    correction_types=active_types,
                    total_offset_ms=time_evidence.total_offset_ms,
                    corrected_start_time_ms=time_evidence.corrected_start_ms,
                    corrected_end_time_ms=time_evidence.corrected_end_ms,
                )
            else:
                evidence = ClockCorrectionEvidence(
                    state=ClockCorrectionEvidenceState.UNSUPPORTED_DRIFT,
                    source_record_ids=time_evidence.source_record_ids,
                    correction_types=active_types,
                )
            clocks.append(
                RetrospectiveSessionClockEvidence(
                    session_record_id=session.record_id,
                    evidence=evidence,
                )
            )
    return evaluate_retrospective_experiment(
        replayed,
        generic_cohort,
        tuple(clocks),
    )


def _source_session_database_id(session: SessionRecord) -> int:
    values = tuple(
        reference.source_record_id
        for reference in session.provenance.source_references
        if reference.source_record_type == "sessions.id"
    )
    if len(values) != 1:
        raise RetrospectiveEvaluationError(
            "Every selected normalized session must retain exactly one OSCAR sessions.id reference."
        )
    try:
        value = int(values[0])
    except ValueError as error:
        raise RetrospectiveEvaluationError(
            "A selected normalized session contains a malformed OSCAR sessions.id reference."
        ) from error
    if value <= 0:
        raise RetrospectiveEvaluationError(
            "A selected normalized session contains a nonpositive OSCAR sessions.id reference."
        )
    return value
