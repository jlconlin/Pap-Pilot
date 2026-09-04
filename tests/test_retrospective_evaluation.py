"""Integration tests for deterministic retrospective evaluation orchestration."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import unittest

from pap_pilot.adapter import (
    OSCAR_COHORT_RECORD_VERSION,
    OscarCohortSelection,
    OscarCorrectionEvidenceState,
    OscarCorrectionType,
    OscarNormalizedCohort,
    OscarSessionTimeEvidence,
    OscarTimeCorrection,
)
from pap_pilot.engine import (
    ClockCorrectionEvidenceState,
    ConfounderEvidenceStatus,
    ConfounderReportStatus,
    ExperimentEvidenceInterval,
    ExperimentPeriod,
    ExperimentProposal,
    ExperimentSetting,
    ExperimentStore,
    IntervalClosure,
    MetricStatus,
    NightAllocationStatus,
    NightRecord,
    OutcomeAction,
    OutcomeClassification,
    ProvenanceRecord,
    ProvenanceValue,
    RETROSPECTIVE_EVALUATION_ENGINE_VERSION,
    RETROSPECTIVE_EVALUATION_RECORD_VERSION,
    RETROSPECTIVE_EVALUATION_SCHEMA_ID,
    RETROSPECTIVE_EVALUATION_SCHEMA_VERSION,
    RetrospectiveCohortEvidence,
    RetrospectiveEvaluationError,
    RetrospectiveEvidenceStatus,
    RetrospectiveNightEvidenceInput,
    RetrospectiveObservation,
    RetrospectiveProtocolInput,
    SessionRecord,
    SettingRecord,
    SignalRecord,
    SignalRepresentation,
    SignalSegmentRecord,
    SleepJournalEntry,
    SourceClass,
    SourceReference,
    TimeBasis,
    evaluate_retrospective_experiment,
    reconstruct_ps_min_experiment_fixture,
    record_retrospective_protocol,
    record_retrospective_user_evidence,
)
from pap_pilot.workflow import evaluate_selected_oscar_retrospective_experiment


_START_MS = 1_800_000_000_000
_DAY_MS = 86_400_000
_SESSION_DURATION_MS = 360_000
_BOUNDARY_MS = _START_MS + 3 * _DAY_MS
_EXPECTED_PATH = Path(__file__).parent / "fixtures" / "retrospective-evaluation-v1.json"


class RetrospectiveEvaluationTests(unittest.TestCase):
    """Exercise the selected cohort, local replay, and complete deterministic pipeline."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "pap_pilot.sqlite3"
        self.oscar_cohort = _cohort()
        self.cohort = _generic_cohort(self.oscar_cohort)
        self.fixture = reconstruct_ps_min_experiment_fixture()
        self.proposal = _proposal(self.fixture, self.cohort)
        self.protocol = _protocol(self.fixture, self.proposal)
        self.inputs = _journal_inputs(self.cohort)
        with ExperimentStore(self.database_path) as store:
            store.create_experiment(self.fixture.experiment)
            store.append_events(self.fixture.history)
            record_retrospective_protocol(
                store,
                self.fixture.experiment.record_id,
                self.cohort,
                self.protocol,
            )
            self.replayed = record_retrospective_user_evidence(
                store,
                self.fixture.experiment.record_id,
                self.cohort,
                self.inputs,
            )

    def test_complete_fixture_produces_stable_evidence_linked_classification(self) -> None:
        result = evaluate_selected_oscar_retrospective_experiment(
            self.oscar_cohort,
            self.replayed,
        )
        repeated = evaluate_selected_oscar_retrospective_experiment(
            self.oscar_cohort,
            self.replayed,
        )
        self.assertEqual(result, repeated)
        self.assertEqual(
            (
                result.schema_id,
                result.schema_version,
                result.record_version,
                result.engine_version,
                result.source_class,
            ),
            (
                RETROSPECTIVE_EVALUATION_SCHEMA_ID,
                RETROSPECTIVE_EVALUATION_SCHEMA_VERSION,
                RETROSPECTIVE_EVALUATION_RECORD_VERSION,
                RETROSPECTIVE_EVALUATION_ENGINE_VERSION,
                SourceClass.COMPANION_DERIVED,
            ),
        )
        self.assertEqual(
            evaluate_retrospective_experiment(
                self.replayed,
                self.cohort,
                tuple(reversed(result.session_clock_evidence)),
            ),
            result,
        )
        self.assertEqual(
            (result.classification.classification, result.classification.action),
            (OutcomeClassification.CLEAR_IMPROVEMENT, OutcomeAction.KEEP),
        )
        self.assertEqual(
            len(result.allocation.included(ExperimentPeriod.BASELINE)),
            3,
        )
        self.assertEqual(
            len(result.allocation.included(ExperimentPeriod.INTERVENTION)),
            3,
        )
        self.assertTrue(
            all(value.status is MetricStatus.CALCULATED for value in result.metric_results)
        )
        self.assertEqual(len(result.metric_results), 12)
        self.assertEqual(len(result.retrospective_night_evidence), 6)
        self.assertEqual(len(result.effective_journal_entries), 6)
        self.assertEqual(result.effective_events, self.replayed.effective_events)

        reports = (
            *result.allocation_structural_quality_reports,
            *result.metric_structural_quality_reports,
            *result.signal_quality_reports,
        )
        report_ids = {value.record_id for value in reports}
        finding_ids = {
            finding.record_id for report in reports for finding in report.findings
        }
        self.assertTrue(
            set(result.classification.quality_report_ids).issubset(report_ids)
        )
        self.assertTrue(
            set(result.classification.quality_finding_ids).issubset(finding_ids)
        )
        self.assertTrue(
            {value.record_id for value in result.selected_nights}.issubset(
                result.source_record_ids
            )
        )
        self.assertTrue(
            {value.record_id for value in result.metric_results}.issubset(
                result.source_record_ids
            )
        )
        self.assertTrue(
            {value.record_id for value in result.effective_events}.issubset(
                result.source_record_ids
            )
        )
        self.assertTrue(finding_ids.issubset(result.source_record_ids))

        expected = json.loads(_EXPECTED_PATH.read_text(encoding="utf-8"))
        observed = {
            "action": result.classification.action.value,
            "allocation_record_id": result.allocation.record_id,
            "allocation_structural_report_count": len(
                result.allocation_structural_quality_reports
            ),
            "baseline_included_night_count": result.classification.baseline_included_night_count,
            "classification": result.classification.classification.value,
            "classification_record_id": result.classification.record_id,
            "effective_event_count": len(result.effective_events),
            "evaluation_record_id": result.record_id,
            "intervention_included_night_count": result.classification.intervention_included_night_count,
            "metric_result_count": len(result.metric_results),
            "metric_structural_report_count": len(
                result.metric_structural_quality_reports
            ),
            "retrospective_night_evidence_count": len(
                result.retrospective_night_evidence
            ),
            "schema_id": result.schema_id,
            "schema_version": result.schema_version,
            "selected_night_count": len(result.selected_nights),
            "signal_quality_report_count": len(result.signal_quality_reports),
        }
        self.assertEqual(observed, expected)

    def test_maps_every_s37a_correction_state_into_corrected_quality(self) -> None:
        result = evaluate_selected_oscar_retrospective_experiment(
            self.oscar_cohort,
            self.replayed,
        )
        self.assertTrue(
            all(
                value.evidence.state is ClockCorrectionEvidenceState.CONFIRMED_NONE
                for value in result.session_clock_evidence
            )
        )
        self.assertTrue(
            all(
                value.time_basis is TimeBasis.CORRECTED_WALL_CLOCK
                for value in result.allocation_structural_quality_reports
            )
        )
        self.assertTrue(
            all(
                value.time_basis is TimeBasis.RAW_RELATIVE
                for value in result.metric_structural_quality_reports
            )
        )

        constant_result = self._evaluate_new_cohort(
            _cohort(constant_session_index=0)
        )
        constant = constant_result.session_clock_evidence[0].evidence
        self.assertEqual(
            (
                constant.state,
                constant.correction_types,
                constant.total_offset_ms,
                constant.corrected_start_time_ms,
                constant.corrected_end_time_ms,
            ),
            (
                ClockCorrectionEvidenceState.SUPPORTED_CONSTANT,
                ("offset",),
                60_000,
                _START_MS + 60_000,
                _START_MS + _SESSION_DURATION_MS + 60_000,
            ),
        )
        self.assertEqual(
            constant_result.classification.classification,
            OutcomeClassification.CLEAR_IMPROVEMENT,
        )

        drift_cohort = _cohort(drift_session_index=0)
        drift_result = self._evaluate_new_cohort(drift_cohort)
        first = drift_result.allocation.nights[0]
        self.assertEqual(first.status, NightAllocationStatus.EXCLUDED)
        self.assertIn("unsupported_drift", first.exclusion_reason_codes)
        self.assertEqual(
            (
                drift_result.classification.classification,
                drift_result.classification.action,
            ),
            (OutcomeClassification.INCONCLUSIVE, OutcomeAction.EXTEND),
        )
        self.assertIn(
            "insufficient_baseline_nights",
            drift_result.classification.reason_codes,
        )
        self.assertEqual(len(drift_result.metric_results), 12)

    def test_refuses_partial_clock_or_mismatched_cohort_evidence(self) -> None:
        complete = evaluate_selected_oscar_retrospective_experiment(
            self.oscar_cohort,
            self.replayed,
        )
        with self.assertRaisesRegex(
            RetrospectiveEvaluationError,
            "cover every selected session exactly once",
        ):
            evaluate_retrospective_experiment(
                self.replayed,
                self.cohort,
                complete.session_clock_evidence[:-1],
            )
        with self.assertRaisesRegex(
            RetrospectiveEvaluationError,
            "link the selected cohort",
        ):
            evaluate_retrospective_experiment(
                self.replayed,
                replace(self.cohort, record_id="cohort:outside"),
                complete.session_clock_evidence,
            )

    def test_requires_complete_effective_user_evidence(self) -> None:
        second_path = Path(self.temporary_directory.name) / "second" / "pap_pilot.sqlite3"
        second_path.parent.mkdir()
        with ExperimentStore(second_path) as store:
            store.create_experiment(self.fixture.experiment)
            store.append_events(self.fixture.history)
            protocol_only = record_retrospective_protocol(
                store,
                self.fixture.experiment.record_id,
                self.cohort,
                self.protocol,
            )
        clocks = evaluate_selected_oscar_retrospective_experiment(
            self.oscar_cohort,
            self.replayed,
        ).session_clock_evidence
        with self.assertRaisesRegex(
            RetrospectiveEvaluationError,
            "cover every selected cohort night",
        ):
            evaluate_retrospective_experiment(protocol_only, self.cohort, clocks)

    def test_status_only_user_evidence_remains_explicit_and_inconclusive(self) -> None:
        oscar_cohort = _cohort()
        generic = _generic_cohort(oscar_cohort)
        status_only = tuple(
            replace(
                value,
                journal_status=RetrospectiveEvidenceStatus.UNAVAILABLE,
                journal_entry=None,
            )
            for value in _journal_inputs(generic)
        )
        result = self._evaluate_new_cohort(
            oscar_cohort,
            inputs=status_only,
        )
        self.assertEqual(result.effective_journal_entries, ())
        self.assertTrue(
            all(
                value.journal_status is RetrospectiveEvidenceStatus.UNAVAILABLE
                for value in result.retrospective_night_evidence
            )
        )
        self.assertEqual(
            (
                result.classification.classification,
                result.classification.action,
            ),
            (OutcomeClassification.INCONCLUSIVE, OutcomeAction.EXTEND),
        )
        self.assertIn(
            "subjective_anchor_missing",
            result.classification.reason_codes,
        )
        self.assertEqual(
            result.classification.confounders.status,
            ConfounderEvidenceStatus.BALANCED,
        )
        self.assertEqual(
            (
                result.classification.confounders.baseline.journaled_night_count,
                result.classification.confounders.intervention.journaled_night_count,
            ),
            (3, 3),
        )
        self.assertFalse(
            any(
                value.event_type.value
                in {
                    "sleep_journal_entry_recorded",
                    "confounder_recorded",
                    "adverse_effect_recorded",
                }
                for value in result.effective_events
            )
        )

    def test_manifest_linked_confounder_does_not_require_a_journal(self) -> None:
        oscar_cohort = _cohort()
        generic = _generic_cohort(oscar_cohort)
        status_only = tuple(
            replace(
                value,
                journal_status=RetrospectiveEvidenceStatus.UNAVAILABLE,
                journal_entry=None,
            )
            for value in _journal_inputs(generic)
        )
        confounder = RetrospectiveObservation(
            description="  Synthetic travel report.  ",
            observed_at_ms=1_900_000_003_000,
            recorded_at_ms=1_900_000_004_000,
            recorded_by="user:synthetic",
            source_record_ids=("user-history:standalone-confounder",),
            source_provenance_ids=("provenance:user:standalone-confounder",),
        )
        status_only = (
            replace(
                status_only[0],
                confounder_status=RetrospectiveEvidenceStatus.REPORTED,
                confounders=(confounder,),
            ),
            *status_only[1:],
        )
        result = self._evaluate_new_cohort(oscar_cohort, inputs=status_only)
        confounder_events = tuple(
            value
            for value in result.effective_events
            if value.event_type.value == "confounder_recorded"
        )
        self.assertEqual(len(confounder_events), 1)
        self.assertEqual(
            result.classification.confounders.baseline.confounded_night_count,
            1,
        )
        self.assertNotIn(
            "confounder_event_without_journal",
            result.classification.reason_codes,
        )

    def test_bundle_and_nested_inputs_are_frozen(self) -> None:
        result = evaluate_selected_oscar_retrospective_experiment(
            self.oscar_cohort,
            self.replayed,
        )
        with self.assertRaises(FrozenInstanceError):
            result.record_id = "changed"
        with self.assertRaises(FrozenInstanceError):
            result.session_clock_evidence[0].session_record_id = "changed"
        with self.assertRaises(TypeError):
            result.source_record_ids[0] = "changed"

    def _evaluate_new_cohort(
        self,
        oscar_cohort: OscarNormalizedCohort,
        *,
        inputs: tuple[RetrospectiveNightEvidenceInput, ...] | None = None,
    ):
        generic = _generic_cohort(oscar_cohort)
        proposal = _proposal(self.fixture, generic)
        protocol = _protocol(self.fixture, proposal)
        selected_inputs = _journal_inputs(generic) if inputs is None else inputs
        path = Path(self.temporary_directory.name) / oscar_cohort.record_id / "pap_pilot.sqlite3"
        path.parent.mkdir()
        with ExperimentStore(path) as store:
            store.create_experiment(self.fixture.experiment)
            store.append_events(self.fixture.history)
            record_retrospective_protocol(
                store,
                self.fixture.experiment.record_id,
                generic,
                protocol,
            )
            replayed = record_retrospective_user_evidence(
                store,
                self.fixture.experiment.record_id,
                generic,
                selected_inputs,
            )
        return evaluate_selected_oscar_retrospective_experiment(
            oscar_cohort,
            replayed,
        )


def _cohort(
    *,
    constant_session_index: int | None = None,
    drift_session_index: int | None = None,
) -> OscarNormalizedCohort:
    if constant_session_index is not None and drift_session_index is not None:
        raise AssertionError("A synthetic session cannot have both correction states.")
    nights = tuple(_night(index) for index in range(6))
    time_evidence = []
    for index, night in enumerate(nights):
        session = night.sessions[0]
        source_session_id = index + 1
        base_sources = {
            "schema_version.version:17",
            "profiles.id:1",
            "machines.id:1",
            f"sessions.id:{source_session_id}",
            "device_time_corrections.machine_id:1:queried",
        }
        if index == constant_session_index:
            correction = OscarTimeCorrection(
                source_correction_id=100 + index,
                machine_database_id=1,
                date_from=night.local_date,
                date_to=night.local_date,
                correction_type=OscarCorrectionType.OFFSET,
                offset_ms=60_000,
                drift_intercept_ms=None,
                drift_slope_encoding=None,
                reason="Synthetic constant offset",
                applied_at="2026-08-01T00:00:00",
                undone_at=None,
            )
            state = OscarCorrectionEvidenceState.SUPPORTED_CONSTANT
            corrections = (correction,)
            base_sources.add(correction.source_record_id)
            total_offset = 60_000
            corrected_start = session.start_time_ms + total_offset
            corrected_end = session.end_time_ms + total_offset
        elif index == drift_session_index:
            correction = OscarTimeCorrection(
                source_correction_id=100 + index,
                machine_database_id=1,
                date_from=night.local_date,
                date_to=night.local_date,
                correction_type=OscarCorrectionType.DRIFT,
                offset_ms=None,
                drift_intercept_ms=0,
                drift_slope_encoding=1.0,
                reason="Synthetic unsupported drift",
                applied_at="2026-08-01T00:00:00",
                undone_at=None,
            )
            state = OscarCorrectionEvidenceState.UNSUPPORTED_DRIFT
            corrections = (correction,)
            base_sources.add(correction.source_record_id)
            total_offset = None
            corrected_start = None
            corrected_end = None
        else:
            state = OscarCorrectionEvidenceState.CONFIRMED_NONE
            corrections = ()
            total_offset = 0
            corrected_start = session.start_time_ms
            corrected_end = session.end_time_ms
        time_evidence.append(
            OscarSessionTimeEvidence(
                record_id=f"time-evidence:{index}",
                session_database_id=source_session_id,
                profile_database_id=1,
                machine_database_id=1,
                local_date=night.local_date,
                raw_start_ms=session.start_time_ms,
                raw_end_ms=session.end_time_ms,
                state=state,
                observed_corrections=corrections,
                total_offset_ms=total_offset,
                corrected_start_ms=corrected_start,
                corrected_end_ms=corrected_end,
                source_record_ids=tuple(base_sources),
            )
        )
    source_records = {
        source
        for value in time_evidence
        for source in value.source_record_ids
    }
    for provenance in _provenances(nights):
        source_records.update(
            f"{reference.source_record_type}:{reference.source_record_id}"
            for reference in provenance.source_references
        )
    if constant_session_index is not None:
        suffix = "constant"
    elif drift_session_index is not None:
        suffix = "drift"
    else:
        suffix = "complete"
    return OscarNormalizedCohort(
        record_id=f"cohort:retrospective:{suffix}",
        selection=OscarCohortSelection(tuple(range(1, 7))),
        nights=nights,
        session_time_evidence=tuple(time_evidence),
        profile_database_id=1,
        machine_database_id=1,
        schema_version=17,
        source_record_ids=tuple(source_records),
        record_version=OSCAR_COHORT_RECORD_VERSION,
    )


def _night(index: int) -> NightRecord:
    start = _START_MS + index * _DAY_MS
    end = start + _SESSION_DURATION_MS
    suffix = f"{index}"
    ps_min = 2.0 if index < 3 else 1.0
    pressure = 13.0 if index < 3 else 12.5
    sample_count = _SESSION_DURATION_MS // 40
    sample_times = tuple(float(start + offset * 40) for offset in range(sample_count))
    flow = SignalRecord(
        record_id=f"signal:{suffix}:flow_rate",
        signal_kind="flow_rate",
        unit="L/min",
        representation=SignalRepresentation.UNIFORM_WAVEFORM,
        segments=(
            SignalSegmentRecord(
                record_id=f"segment:{suffix}:flow_rate",
                start_time_ms=start,
                end_time_ms=end,
                interval_closure=IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                sample_times_ms=sample_times,
                values=(10.0,) * sample_count,
                sample_interval_ms=40.0,
                provenance=_provenance(
                    f"segment-{suffix}-flow",
                    {
                        "segment.gain_per_raw_unit": 0.1,
                        "segment.offset": 0.0,
                    },
                ),
            ),
        ),
        provenance=_provenance(
            f"signal-{suffix}-flow",
            {"signal.availability": "available"},
        ),
    )
    mask_pressure = SignalRecord(
        record_id=f"signal:{suffix}:mask_pressure",
        signal_kind="mask_pressure",
        unit="cm H₂O",
        representation=SignalRepresentation.UNIFORM_WAVEFORM,
        segments=(
            SignalSegmentRecord(
                record_id=f"segment:{suffix}:mask_pressure",
                start_time_ms=start,
                end_time_ms=end,
                interval_closure=IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                sample_times_ms=sample_times,
                values=(pressure,) * sample_count,
                sample_interval_ms=40.0,
                provenance=_provenance(
                    f"segment-{suffix}-pressure",
                    {
                        "segment.gain_per_raw_unit": 0.1,
                        "segment.offset": 0.0,
                    },
                ),
            ),
        ),
        provenance=_provenance(
            f"signal-{suffix}-pressure",
            {"signal.availability": "available"},
        ),
    )
    leak = SignalRecord(
        record_id=f"signal:{suffix}:leak_rate",
        signal_kind="leak_rate",
        unit="L/min",
        representation=SignalRepresentation.TIMED_UPDATES,
        segments=(
            SignalSegmentRecord(
                record_id=f"segment:{suffix}:leak_rate",
                start_time_ms=start,
                end_time_ms=end,
                interval_closure=IntervalClosure.START_AND_END_INCLUSIVE,
                sample_times_ms=(float(start), float(end)),
                values=(5.0, 5.0),
                sample_interval_ms=None,
                provenance=_provenance(
                    f"segment-{suffix}-leak",
                    {
                        "segment.gain_per_raw_unit": 0.1,
                        "segment.offset": 0.0,
                    },
                ),
            ),
        ),
        provenance=_provenance(
            f"signal-{suffix}-leak",
            {"signal.availability": "available"},
        ),
        value_semantics="unintentional",
    )
    session = SessionRecord(
        record_id=f"session:{suffix}",
        device_id="device:synthetic",
        start_time_ms=start,
        end_time_ms=end,
        settings=_settings(suffix, ps_min),
        events=(),
        signals=(flow, leak, mask_pressure),
        provenance=_provenance(
            f"session-{suffix}",
            {"events.completeness": "unknown"},
            session_database_id=index + 1,
        ),
    )
    return NightRecord(
        record_id=f"night:{suffix}",
        local_date=f"2026-08-{index + 1:02d}",
        timezone="America/Denver",
        day_boundary_local_time="12:00:00",
        sessions=(session,),
        provenance=_provenance(f"night-{suffix}"),
    )


def _settings(suffix: str, ps_min: float) -> tuple[SettingRecord, ...]:
    values = (
        ("therapy_mode_code", 6, None),
        ("loader_mode_code", 7, None),
        ("epap", 10.0, "cm H₂O"),
        ("ps_min", ps_min, "cm H₂O"),
        ("ps_max", 5.0, "cm H₂O"),
        ("max_ipap", 15.0, "cm H₂O"),
    )
    return tuple(
        SettingRecord(
            record_id=f"setting:{suffix}:{name}",
            name=name,
            value=value,
            unit=unit,
            provenance=_provenance(f"setting-{suffix}-{name}"),
        )
        for name, value, unit in values
    )


def _provenance(
    name: str,
    values: dict[str, object] | None = None,
    *,
    session_database_id: int | None = None,
) -> ProvenanceRecord:
    references = [SourceReference("fixture", name)]
    if session_database_id is not None:
        references.append(SourceReference("sessions.id", str(session_database_id)))
    source_values = tuple(
        ProvenanceValue(
            key,
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        for key, value in (values or {}).items()
    )
    return ProvenanceRecord(
        record_id=f"provenance:{name}",
        source_classes=(
            SourceClass.MACHINE_RECORDED,
            SourceClass.OSCAR_NORMALIZED,
        ),
        source_system="synthetic_fixture",
        source_references=tuple(references),
        source_values=source_values,
    )


def _provenances(nights: tuple[NightRecord, ...]) -> tuple[ProvenanceRecord, ...]:
    values = []
    for night in nights:
        values.append(night.provenance)
        for session in night.sessions:
            values.append(session.provenance)
            values.extend(setting.provenance for setting in session.settings)
            values.extend(event.provenance for event in session.events)
            for signal in session.signals:
                values.append(signal.provenance)
                values.extend(segment.provenance for segment in signal.segments)
    return tuple(values)


def _generic_cohort(cohort: OscarNormalizedCohort) -> RetrospectiveCohortEvidence:
    return RetrospectiveCohortEvidence(
        record_id=cohort.record_id,
        nights=cohort.nights,
        source_record_ids=cohort.source_record_ids,
    )


def _proposal(fixture, cohort: RetrospectiveCohortEvidence) -> ExperimentProposal:
    first_night = cohort.nights[0]
    first_session = first_night.sessions[0]
    baseline_settings = tuple(
        ExperimentSetting(value.name, value.value, value.unit)
        for value in first_session.settings
    )
    flow = next(
        value for value in first_session.signals if value.signal_kind == "flow_rate"
    )
    segment = flow.segments[0]
    interval_sources = (
        first_night.record_id,
        first_session.record_id,
        flow.record_id,
        segment.record_id,
    )
    return ExperimentProposal(
        problem_event_id=fixture.history[0].record_id,
        hypothesis_event_id=fixture.history[1].record_id,
        baseline_local_dates=tuple(value.local_date for value in cohort.nights[:3]),
        baseline_settings=baseline_settings,
        proposed_change=fixture.known_change,
        settings_held_fixed=tuple(
            value for value in baseline_settings if value.name != "ps_min"
        ),
        evidence_record_ids=(
            cohort.record_id,
            *(value.record_id for value in cohort.nights[:3]),
            first_session.record_id,
            flow.record_id,
            segment.record_id,
        ),
        representative_intervals=(
            ExperimentEvidenceInterval(
                night_record_id=first_night.record_id,
                session_record_id=first_session.record_id,
                start_time_ms=segment.start_time_ms,
                end_time_ms=segment.end_time_ms,
                source_record_ids=interval_sources,
            ),
        ),
        expected_objective_effects=(
            "Lower independently calculated Mask Pressure above fixed EPAP",
        ),
        expected_subjective_effects=("Improved morning journal outcomes",),
        minimum_valid_nights=3,
        invalid_night_criteria=("Insufficient required evidence",),
        possible_adverse_effects=("Reduced ventilatory support",),
        stop_conditions=("Material worsening",),
        revert_conditions=("Sustained worsening",),
    )


def _protocol(fixture, proposal: ExperimentProposal) -> RetrospectiveProtocolInput:
    return RetrospectiveProtocolInput(
        proposal=proposal,
        user_accepted=True,
        acceptance_rationale="Synthetic fixture acceptance",
        confirmed_change=fixture.known_change,
        boundary_user_confirmed=True,
        applied_at_ms=_BOUNDARY_MS,
        proposal_recorded_at_ms=1_900_000_000_000,
        accepted_at_ms=1_900_000_000_001,
        confirmed_at_ms=1_900_000_000_002,
        recorded_by="user:synthetic",
        user_source_record_ids=("user-confirmation:synthetic",),
        user_provenance_ids=("provenance:user:synthetic",),
    )


def _journal_inputs(
    cohort: RetrospectiveCohortEvidence,
) -> tuple[RetrospectiveNightEvidenceInput, ...]:
    values = []
    for index, night in enumerate(cohort.nights):
        intervention = index >= 3
        journal = SleepJournalEntry(
            record_id=f"journal:{index}",
            night_record_id=night.record_id,
            reported_at_ms=1_900_000_001_000 + index,
            reported_by="user:synthetic",
            awakenings_count=1 if intervention else 2,
            sleep_quality=4 if intervention else 3,
            morning_energy=4 if intervention else 3,
            daytime_tiredness=2 if intervention else 3,
            confounder_status=ConfounderReportStatus.NONE_REPORTED,
            confounders=(),
            original_note=f"  Synthetic original note {index}.  ",
            source_provenance_ids=(f"provenance:user:journal:{index}",),
        )
        values.append(
            RetrospectiveNightEvidenceInput(
                night_record_id=night.record_id,
                journal_status=RetrospectiveEvidenceStatus.REPORTED,
                journal_entry=journal,
                confounder_status=RetrospectiveEvidenceStatus.NONE_REPORTED,
                confounders=(),
                adverse_effect_status=RetrospectiveEvidenceStatus.NONE_REPORTED,
                adverse_effects=(),
                recorded_at_ms=1_900_000_002_000 + index,
                recorded_by="user:synthetic",
                source_record_ids=(f"user-history:{index}",),
                source_provenance_ids=(f"provenance:user:manifest:{index}",),
            )
        )
    return tuple(values)


if __name__ == "__main__":
    unittest.main()
