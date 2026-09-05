from dataclasses import replace
import unittest

from pap_pilot.engine import (
    ExperimentActionPayload,
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentProposedPayload,
    ExperimentRecord,
    ExperimentSetting,
    ExperimentSettingChange,
    ExperimentProposal,
    ExperimentRevisedPayload,
    HypothesisDraftedPayload,
    ProblemRecordedPayload,
    ProspectiveLifecycleError,
    ProspectiveLifecycleStatus,
    SettingChangeConfirmedPayload,
    SourceClass,
    append_prospective_lifecycle_event,
    replay_prospective_lifecycle,
)


class ProspectiveLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.experiment = ExperimentRecord("experiment:one", "Prospective trial", 1, "user:local", ("source:one",))
        settings = (
            ExperimentSetting("therapy_mode_code", 6), ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"), ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_max", 5.0, "cm H₂O"), ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        self.proposal = ExperimentProposal(
            "event:problem", "event:hypothesis", ("2026-01-01",), settings,
            ExperimentSettingChange(settings[3], ExperimentSetting("ps_min", 1.0, "cm H₂O")), settings[:3] + settings[4:],
            ("night", "session"), (ExperimentEvidenceInterval("night", "session", 1, 2, ("night", "session")),), ("objective",), ("subjective",), 3, ("invalid",), ("adverse",), ("stop",), ("revert",),
        )

    def event(self, sequence: int, kind: ExperimentEventType, payload: object, record_id: str) -> ExperimentEvent:
        return ExperimentEvent(record_id, self.experiment.record_id, sequence, kind, sequence, "user:local", payload, SourceClass.USER_REPORTED, (self.experiment.record_id,), ("source:one",))

    def test_complete_lifecycle_replays_to_reverted(self) -> None:
        events = (
            self.event(1, ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), "event:problem"),
            self.event(2, ExperimentEventType.HYPOTHESIS_DRAFTED, HypothesisDraftedPayload("Hypothesis", ("Variation",)), "event:hypothesis"),
            self.event(3, ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(self.proposal), "event:proposal"),
            self.event(4, ExperimentEventType.EXPERIMENT_ACCEPTED, ExperimentDecisionPayload("event:proposal", "Accept"), "event:accepted"),
            self.event(5, ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED, SettingChangeConfirmedPayload("event:accepted", self.proposal.proposed_change, 5), "event:applied"),
            self.event(6, ExperimentEventType.EXPERIMENT_EXTENDED, ExperimentActionPayload("More nights", 6, "2026-02-01"), "event:extended"),
            self.event(7, ExperimentEventType.EXPERIMENT_STOPPED, ExperimentActionPayload("Stop review", 7), "event:stopped"),
            self.event(8, ExperimentEventType.EXPERIMENT_REVERTED, ExperimentActionPayload("Restore prior", 8), "event:reverted"),
        )
        state = replay_prospective_lifecycle(self.experiment, events)
        self.assertEqual(state.status, ProspectiveLifecycleStatus.REVERTED)
        self.assertEqual(state.applied_event_id, "event:applied")

    def test_invalid_transition_is_rejected_without_appending(self) -> None:
        problem = self.event(1, ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), "event:problem")
        with self.assertRaises(ProspectiveLifecycleError):
            append_prospective_lifecycle_event(self.experiment, (problem,), self.event(2, ExperimentEventType.EXPERIMENT_REVERTED, ExperimentActionPayload("No application", 2), "event:reverted"))
        self.assertEqual((problem,), (problem,))

    def test_revision_then_rejection_is_supported(self) -> None:
        problem = self.event(1, ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Problem"), "event:problem")
        hypothesis = self.event(2, ExperimentEventType.HYPOTHESIS_DRAFTED, HypothesisDraftedPayload("Hypothesis", ("Variation",)), "event:hypothesis")
        proposed = self.event(3, ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(self.proposal), "event:proposal")
        revised = self.event(4, ExperimentEventType.EXPERIMENT_REVISED, ExperimentRevisedPayload("event:proposal", self.proposal), "event:revision")
        rejected = self.event(5, ExperimentEventType.EXPERIMENT_REJECTED, ExperimentDecisionPayload("event:revision", "Insufficient evidence"), "event:rejected")
        state = replay_prospective_lifecycle(self.experiment, (problem, hypothesis, proposed, revised, rejected))
        self.assertEqual(state.status, ProspectiveLifecycleStatus.REJECTED)

    def test_corrections_remain_in_ledger_while_replay_uses_effective_events(self) -> None:
        problem = self.event(1, ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Original"), "event:problem")
        correction = self.event(2, ExperimentEventType.PROBLEM_RECORDED, ProblemRecordedPayload("Corrected"), "event:problem-correction")
        correction = replace(correction, correction_of_event_id="event:problem")
        state = replay_prospective_lifecycle(self.experiment, (problem, correction))
        self.assertEqual(len(state.effective_events), 1)
        self.assertEqual(state.effective_events[0].record_id, "event:problem-correction")


if __name__ == "__main__":
    unittest.main()
