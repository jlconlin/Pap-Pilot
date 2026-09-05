from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from pap_pilot.api import PS_MIN_JOURNAL_PATH, PS_MIN_EXPERIMENT_HISTORY_PATH, create_app
from pap_pilot.engine import (
    ExperimentActionPayload,
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentProposedPayload,
    ExperimentProposal,
    ExperimentSetting,
    ExperimentSettingChange,
    ExperimentStore,
    HypothesisDraftedPayload,
    ProblemRecordedPayload,
    ProspectiveNightEvidence,
    ProspectiveSafetyEvidence,
    SettingChangeConfirmedPayload,
    SourceClass,
    SleepJournalEntry,
    ExperimentRecord,
    evaluate_prospective_safety,
    reconstruct_ps_min_experiment_fixture,
    replay_prospective_lifecycle,
)


class ProspectiveVerticalSliceTests(unittest.TestCase):
    def test_synthetic_gate_lifecycle_journal_monitoring_and_replay(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()
        experiment = fixture.experiment
        settings = (
            ExperimentSetting("therapy_mode_code", 6), ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"), ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_max", 5.0, "cm H₂O"), ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        proposal = ExperimentProposal(
            "event:ps-min-retrospective:problem", "event:ps-min-retrospective:hypothesis", ("2026-01-01",), settings,
            ExperimentSettingChange(settings[3], ExperimentSetting("ps_min", 1.0, "cm H₂O")), settings[:3] + settings[4:],
            ("night:one", "session:one"), (ExperimentEvidenceInterval("night:one", "session:one", 1, 2, ("night:one", "session:one")),),
            ("objective",), ("subjective",), 3, ("invalid",), ("adverse",), ("stop",), ("revert",),
        )
        nights = tuple(ProspectiveNightEvidence(f"2026-01-0{index}", 300_000) for index in range(1, 4))
        gate = evaluate_prospective_safety(proposal, ProspectiveSafetyEvidence(nights, nights, settings))
        self.assertTrue(gate.eligible)
        def event(sequence: int, kind: ExperimentEventType, payload: object, record_id: str) -> ExperimentEvent:
            return ExperimentEvent(record_id, experiment.record_id, sequence, kind, sequence, "user:local", payload, SourceClass.USER_REPORTED, (experiment.record_id,), ("provenance:synthetic",))
        lifecycle_events = (
            event(3, ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(proposal), "event:proposal"),
            event(4, ExperimentEventType.EXPERIMENT_ACCEPTED, ExperimentDecisionPayload("event:proposal", "Synthetic acceptance"), "event:accepted"),
            event(5, ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED, SettingChangeConfirmedPayload("event:accepted", proposal.proposed_change, 5), "event:applied"),
            event(6, ExperimentEventType.EXPERIMENT_KEPT, ExperimentActionPayload("Synthetic keep", 6), "event:kept"),
        )
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "pap_pilot.sqlite3"
            with ExperimentStore(database_path) as store:
                store.create_experiment(experiment)
                store.append_events(fixture.history)
                store.append_events(lifecycle_events)
                state = replay_prospective_lifecycle(experiment, store.read_history(experiment.record_id))
                self.assertEqual(state.status.value, "kept")
            with TestClient(create_app(database_path=database_path)) as client:
                journal = client.post(PS_MIN_JOURNAL_PATH, json={"night_record_id": "night:one", "sleep_quality": 4, "original_note": "Synthetic note"})
                self.assertEqual(journal.status_code, 201)
                monitoring = client.get(PS_MIN_EXPERIMENT_HISTORY_PATH).json()["monitoring"]
                self.assertEqual(monitoring["lifecycle_status"], "kept")
                self.assertEqual(monitoring["reported_night_count"], 1)
                self.assertIn("revert", monitoring["available_actions"])
                self.assertFalse(monitoring["automatic_device_actions"])


if __name__ == "__main__":
    unittest.main()
