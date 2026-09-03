"""Focused tests for versioned experiment and append-only event schemas."""

from dataclasses import FrozenInstanceError, replace
import math
import unittest

from pap_pilot.engine import (
    EXPERIMENT_EVENT_RECORD_VERSION,
    EXPERIMENT_EVENT_SCHEMA_ID,
    EXPERIMENT_EVENT_SCHEMA_VERSION,
    EXPERIMENT_RECORD_VERSION,
    EXPERIMENT_SCHEMA_ID,
    EXPERIMENT_SCHEMA_VERSION,
    EvaluationIssuedPayload,
    EvaluationSupersededPayload,
    ExperimentActionPayload,
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentModelError,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentRecord,
    ExperimentRevisedPayload,
    ExperimentSetting,
    ExperimentSettingChange,
    HypothesisDraftedPayload,
    NoteRecordedPayload,
    ObservationRecordedPayload,
    ProblemRecordedPayload,
    SettingChangeConfirmedPayload,
    SleepJournalEntryRecordedPayload,
    SourceClass,
    append_experiment_event,
    validate_experiment_history,
)


class ExperimentModelTests(unittest.TestCase):
    """Verify structural completeness, additive correction, and immutability."""

    def setUp(self) -> None:
        self.experiment = ExperimentRecord(
            record_id="experiment:ps-min-2-to-1",
            title="Retrospective PS Min 2 to 1",
            created_at_ms=1_788_300_000_000,
            created_by="user:local",
            source_provenance_ids=("provenance:user", "provenance:engine"),
        )
        self.baseline_settings = (
            ExperimentSetting("therapy_mode_code", 6),
            ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"),
            ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_max", 5.0, "cm H₂O"),
            ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        self.change = ExperimentSettingChange(
            previous=ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            proposed=ExperimentSetting("ps_min", 1.0, "cm H₂O"),
        )
        self.proposal = ExperimentProposal(
            problem_event_id="event:problem",
            hypothesis_event_id="event:hypothesis",
            baseline_local_dates=("2026-08-29", "2026-08-28"),
            baseline_settings=self.baseline_settings,
            proposed_change=self.change,
            settings_held_fixed=tuple(setting for setting in self.baseline_settings if setting.name != "ps_min"),
            evidence_record_ids=("night:baseline", "session:baseline", "signal:flow", "metric:pressure"),
            representative_intervals=(
                ExperimentEvidenceInterval(
                    night_record_id="night:baseline",
                    session_record_id="session:baseline",
                    start_time_ms=1_000,
                    end_time_ms=61_000,
                    source_record_ids=("night:baseline", "session:baseline", "signal:flow"),
                ),
            ),
            expected_objective_effects=("Lower Mask Pressure above fixed EPAP",),
            expected_subjective_effects=("Fewer remembered awakenings",),
            minimum_valid_nights=3,
            invalid_night_criteria=("Insufficient required signal coverage",),
            possible_adverse_effects=("Reduced ventilatory support",),
            stop_conditions=("Material worsening of breathing or symptoms",),
            revert_conditions=("Sustained subjective or objective worsening",),
        )

    def test_experiment_identity_is_explicitly_versioned(self) -> None:
        self.assertEqual(
            (
                self.experiment.schema_id,
                self.experiment.schema_version,
                self.experiment.record_version,
            ),
            (EXPERIMENT_SCHEMA_ID, EXPERIMENT_SCHEMA_VERSION, EXPERIMENT_RECORD_VERSION),
        )
        self.assertEqual(self.experiment.source_provenance_ids, ("provenance:engine", "provenance:user"))

    def test_proposal_carries_every_structural_design_field_from_the_plan(self) -> None:
        self.assertEqual(self.proposal.baseline_local_dates, ("2026-08-28", "2026-08-29"))
        self.assertEqual(self.proposal.proposed_change.previous.value, 2.0)
        self.assertEqual(self.proposal.proposed_change.proposed.value, 1.0)
        self.assertEqual({value.name for value in self.proposal.settings_held_fixed}, {"therapy_mode_code", "loader_mode_code", "epap", "ps_max", "max_ipap"})
        self.assertTrue(self.proposal.evidence_record_ids)
        self.assertTrue(self.proposal.representative_intervals)
        self.assertTrue(self.proposal.expected_objective_effects)
        self.assertTrue(self.proposal.expected_subjective_effects)
        self.assertGreater(self.proposal.minimum_valid_nights, 0)
        self.assertTrue(self.proposal.invalid_night_criteria)
        self.assertTrue(self.proposal.possible_adverse_effects)
        self.assertTrue(self.proposal.stop_conditions)
        self.assertTrue(self.proposal.revert_conditions)

    def test_event_vocabulary_covers_the_plan_minimum_and_append_only_notes(self) -> None:
        self.assertEqual(
            {value.value for value in ExperimentEventType},
            {
                "problem_recorded",
                "hypothesis_drafted",
                "experiment_proposed",
                "experiment_accepted",
                "experiment_rejected",
                "experiment_revised",
                "setting_change_confirmed_applied",
                "sleep_journal_entry_recorded",
                "confounder_recorded",
                "adverse_effect_recorded",
                "experiment_stopped",
                "experiment_extended",
                "experiment_kept",
                "experiment_reverted",
                "evaluation_issued",
                "evaluation_superseded",
                "note_recorded",
            },
        )

    def test_every_minimum_event_type_has_a_valid_typed_payload(self) -> None:
        action = ExperimentActionPayload("User decision", 1_788_400_000_000)
        history_proposal = replace(self.proposal, problem_event_id="event:problem", hypothesis_event_id="event:hypothesis")
        payloads = {
            ExperimentEventType.PROBLEM_RECORDED: ProblemRecordedPayload("Repeated awakenings despite low machine-reported AHI"),
            ExperimentEventType.HYPOTHESIS_DRAFTED: HypothesisDraftedPayload("PS Min may contribute to disruptive support", ("Normal variability", "Mask leak")),
            ExperimentEventType.EXPERIMENT_PROPOSED: ExperimentProposedPayload(history_proposal),
            ExperimentEventType.EXPERIMENT_ACCEPTED: ExperimentDecisionPayload("event:proposal", "Accepted for retrospective reconstruction"),
            ExperimentEventType.EXPERIMENT_REJECTED: ExperimentDecisionPayload("event:proposal", "Evidence was not adequate"),
            ExperimentEventType.EXPERIMENT_REVISED: ExperimentRevisedPayload("event:proposal", history_proposal),
            ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED: SettingChangeConfirmedPayload("event:accepted", self.change, 1_788_350_000_000),
            ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED: SleepJournalEntryRecordedPayload("journal:one", "night:intervention"),
            ExperimentEventType.CONFOUNDER_RECORDED: ObservationRecordedPayload("Travel night", 1_788_360_000_000, "night:intervention"),
            ExperimentEventType.ADVERSE_EFFECT_RECORDED: ObservationRecordedPayload("Morning discomfort", 1_788_370_000_000, "night:intervention"),
            ExperimentEventType.EXPERIMENT_STOPPED: action,
            ExperimentEventType.EXPERIMENT_EXTENDED: ExperimentActionPayload("Collect more valid nights", 1_788_400_000_000, "2026-09-10"),
            ExperimentEventType.EXPERIMENT_KEPT: action,
            ExperimentEventType.EXPERIMENT_REVERTED: action,
            ExperimentEventType.EVALUATION_ISSUED: EvaluationIssuedPayload("evaluation:one"),
            ExperimentEventType.EVALUATION_SUPERSEDED: EvaluationSupersededPayload("event:evaluation-one", "evaluation:two"),
            ExperimentEventType.NOTE_RECORDED: NoteRecordedPayload("Retained note", "event:evaluation-one"),
        }
        record_ids = {
            ExperimentEventType.PROBLEM_RECORDED: "event:problem",
            ExperimentEventType.HYPOTHESIS_DRAFTED: "event:hypothesis",
            ExperimentEventType.EXPERIMENT_PROPOSED: "event:proposal",
            ExperimentEventType.EXPERIMENT_ACCEPTED: "event:accepted",
            ExperimentEventType.EVALUATION_ISSUED: "event:evaluation-one",
        }
        history = ()
        for sequence, event_type in enumerate(ExperimentEventType, start=1):
            history = append_experiment_event(self.experiment, history, self._event(event_type, payloads[event_type], sequence, record_id=record_ids.get(event_type)))

        self.assertEqual(len(history), len(ExperimentEventType))
        self.assertEqual(tuple(event.event_type for event in history), tuple(ExperimentEventType))
        self.assertTrue(all(event.schema_id == EXPERIMENT_EVENT_SCHEMA_ID for event in history))
        self.assertTrue(all(event.schema_version == EXPERIMENT_EVENT_SCHEMA_VERSION for event in history))
        self.assertTrue(all(event.record_version == EXPERIMENT_EVENT_RECORD_VERSION for event in history))

    def test_correction_appends_same_type_and_preserves_original_event(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original wording"), 1, record_id="event:problem-original")
        history = append_experiment_event(self.experiment, (), original)
        corrected = self._event(
            ExperimentEventType.PROBLEM_RECORDED,
            ProblemRecordedPayload("Corrected wording"),
            2,
            record_id="event:problem-correction",
            correction_of_event_id=original.record_id,
        )

        corrected_history = append_experiment_event(self.experiment, history, corrected)

        self.assertEqual(history, (original,))
        self.assertEqual(corrected_history, (original, corrected))
        self.assertEqual(corrected_history[1].correction_of_event_id, original.record_id)
        self.assertEqual(corrected_history[0].payload.problem, "Original wording")

    def test_destructive_replacement_is_rejected_by_append_contract(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original wording"), 1, record_id="event:problem")
        history = append_experiment_event(self.experiment, (), original)
        replacement = replace(original, payload=ProblemRecordedPayload("Silently replaced wording"))

        with self.assertRaisesRegex(ExperimentModelError, "appended with contiguous sequence numbers"):
            append_experiment_event(self.experiment, history, replacement)

        duplicate_identifier = replace(replacement, sequence_number=2)
        with self.assertRaisesRegex(ExperimentModelError, "cannot be replaced"):
            append_experiment_event(self.experiment, history, duplicate_identifier)

    def test_correction_requires_an_earlier_same_type_target(self) -> None:
        original = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original wording"), 1, record_id="event:problem")
        history = (original,)
        missing_target = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Correction"), 2, correction_of_event_id="event:missing")
        wrong_type = self._event(ExperimentEventType.HYPOTHESIS_DRAFTED, HypothesisDraftedPayload("Correction", ("Alternative",)), 2, correction_of_event_id=original.record_id)

        with self.assertRaisesRegex(ExperimentModelError, "earlier event"):
            append_experiment_event(self.experiment, history, missing_target)
        with self.assertRaisesRegex(ExperimentModelError, "retain the corrected event type"):
            append_experiment_event(self.experiment, history, wrong_type)

    def test_history_rejects_cross_experiment_and_noncontiguous_events(self) -> None:
        first = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), 1)
        wrong_experiment = replace(self.experiment, record_id="experiment:other")
        skipped = self._event(ExperimentEventType.HYPOTHESIS_DRAFTED, HypothesisDraftedPayload("Hypothesis", ("Alternative",)), 3)

        with self.assertRaisesRegex(ExperimentModelError, "belong to its experiment"):
            validate_experiment_history(wrong_experiment, (first,))
        with self.assertRaisesRegex(ExperimentModelError, "contiguous sequence numbers"):
            validate_experiment_history(self.experiment, (first, skipped))

    def test_history_rejects_dangling_or_wrong_type_payload_references(self) -> None:
        problem = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), 1, record_id="event:problem")
        hypothesis = self._event(ExperimentEventType.HYPOTHESIS_DRAFTED, HypothesisDraftedPayload("Hypothesis", ("Alternative",)), 2, record_id="event:hypothesis")
        dangling = replace(self.proposal, problem_event_id="event:missing", hypothesis_event_id=hypothesis.record_id)
        wrong_type = replace(self.proposal, problem_event_id=hypothesis.record_id, hypothesis_event_id=hypothesis.record_id)

        with self.assertRaisesRegex(ExperimentModelError, "problem reference"):
            validate_experiment_history(self.experiment, (problem, hypothesis, self._event(ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(dangling), 3)))
        with self.assertRaisesRegex(ExperimentModelError, "problem reference"):
            validate_experiment_history(self.experiment, (problem, hypothesis, self._event(ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(wrong_type), 3)))

    def test_event_type_requires_its_exact_payload_schema(self) -> None:
        with self.assertRaisesRegex(ExperimentModelError, "payload does not match"):
            self._event(ExperimentEventType.PROBLEM_RECORDED, EvaluationIssuedPayload("evaluation:wrong"), 1)

    def test_extension_date_is_required_only_for_extension_events(self) -> None:
        without_date = ExperimentActionPayload("Need more data", 1_788_400_000_000)
        with_date = ExperimentActionPayload("Stop now", 1_788_400_000_000, "2026-09-10")

        with self.assertRaisesRegex(ExperimentModelError, "requires its new end date"):
            self._event(ExperimentEventType.EXPERIMENT_EXTENDED, without_date, 1)
        with self.assertRaisesRegex(ExperimentModelError, "Only an experiment extension"):
            self._event(ExperimentEventType.EXPERIMENT_STOPPED, with_date, 1)

    def test_setting_change_is_structurally_single_variable_without_policy_rules(self) -> None:
        with self.assertRaisesRegex(ExperimentModelError, "one setting identity"):
            ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("epap", 9.0, "cm H₂O"))
        with self.assertRaisesRegex(ExperimentModelError, "distinct"):
            ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 2.0, "cm H₂O"))

    def test_proposal_rejects_incomplete_or_internally_inconsistent_designs(self) -> None:
        with self.assertRaisesRegex(ExperimentModelError, "pre-change"):
            replace(self.proposal, baseline_settings=tuple(setting for setting in self.baseline_settings if setting.name != "ps_min"))
        with self.assertRaisesRegex(ExperimentModelError, "cannot also be held fixed"):
            replace(self.proposal, settings_held_fixed=(*self.proposal.settings_held_fixed, self.change.previous))
        with self.assertRaisesRegex(ExperimentModelError, "minimum valid-night"):
            replace(self.proposal, minimum_valid_nights=0)
        with self.assertRaisesRegex(ExperimentModelError, "stop conditions"):
            replace(self.proposal, stop_conditions=())

    def test_invalid_versions_values_and_evidence_fail_safely(self) -> None:
        with self.assertRaisesRegex(ExperimentModelError, "unsupported"):
            replace(self.experiment, record_version=2)
        with self.assertRaisesRegex(ExperimentModelError, "unsupported"):
            replace(self.experiment, schema_version=True)
        with self.assertRaisesRegex(ExperimentModelError, "finite JSON scalar"):
            ExperimentSetting("ps_min", math.nan, "cm H₂O")
        with self.assertRaisesRegex(ExperimentModelError, "positive and half-open"):
            ExperimentEvidenceInterval("night:one", "session:one", 100, 100, ("night:one", "session:one"))
        with self.assertRaisesRegex(ExperimentModelError, "must include"):
            ExperimentEvidenceInterval("night:one", "session:one", 100, 200, ("night:one",))
        event = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), 1)
        with self.assertRaisesRegex(ExperimentModelError, "unsupported"):
            replace(event, schema_version=2)
        with self.assertRaisesRegex(ExperimentModelError, "unsupported"):
            replace(event, record_version=True)

    def test_records_and_histories_are_immutable(self) -> None:
        event = self._event(ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), 1)
        history = append_experiment_event(self.experiment, (), event)

        with self.assertRaises(FrozenInstanceError):
            self.experiment.title = "Changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            event.payload.problem = "Changed"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            history.append(event)  # type: ignore[attr-defined]

    def _event(
        self,
        event_type: ExperimentEventType,
        payload,
        sequence_number: int,
        *,
        record_id: str | None = None,
        correction_of_event_id: str | None = None,
    ) -> ExperimentEvent:
        identifier = record_id or f"event:{sequence_number}:{event_type.value}"
        return ExperimentEvent(
            record_id=identifier,
            experiment_record_id=self.experiment.record_id,
            sequence_number=sequence_number,
            event_type=event_type,
            recorded_at_ms=1_788_300_000_000 + sequence_number,
            recorded_by="user:local",
            payload=payload,
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=(self.experiment.record_id,),
            source_provenance_ids=("provenance:user",),
            correction_of_event_id=correction_of_event_id,
        )


if __name__ == "__main__":
    unittest.main()
