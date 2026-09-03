"""Focused replay and API tests for append-only boundary corrections."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from pap_pilot.api import PS_MIN_BOUNDARY_CORRECTION_PATH, PS_MIN_EXPERIMENT_HISTORY_PATH, create_app
from pap_pilot.engine import ExperimentDecisionPayload, ExperimentEvent, ExperimentEventType, ExperimentEvidenceInterval, ExperimentProposal, ExperimentProposedPayload, ExperimentSetting, ExperimentStore, ExperimentStoreError, NoteRecordedPayload, SettingChangeConfirmedPayload, SourceClass, build_boundary_correction_events, reconstruct_ps_min_experiment_fixture


class BoundaryCorrectionTests(unittest.TestCase):
    """Prove corrections and notes append while replay selects the new boundary."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "pap_pilot.sqlite3"
        with TestClient(create_app(database_path=self.database_path)) as client:
            self.assertEqual(client.get(PS_MIN_EXPERIMENT_HISTORY_PATH).status_code, 200)
        self.fixture = reconstruct_ps_min_experiment_fixture()
        self.boundary = self._append_original_boundary()

    def test_engine_and_store_preserve_history_and_replay_the_corrected_boundary(self) -> None:
        with ExperimentStore(self.database_path) as store:
            before = store.replay(self.fixture.experiment.record_id)
            correction, note = build_boundary_correction_events(
                before,
                corrected_event_id=self.boundary.record_id,
                applied_at_ms=1_788_450_000_000,
                note="The first timestamp used the start of the calendar day; this is the actual change time.",
                recorded_at_ms=1_788_500_000_000,
                correction_event_id="event:boundary-correction",
                note_event_id="event:boundary-note",
            )
            invalid_note = replace(note, payload=NoteRecordedPayload("Invalid link", "event:missing"))
            with self.assertRaises(ExperimentStoreError):
                store.append_events((correction, invalid_note))
            self.assertEqual(store.replay(self.fixture.experiment.record_id), before)
            store.append_events((correction, note))
            replayed = store.replay(self.fixture.experiment.record_id)

        self.assertEqual(replayed.history[-2:], (correction, note))
        self.assertIn(self.boundary, replayed.history)
        self.assertNotIn(self.boundary, replayed.effective_events)
        self.assertEqual(replayed.latest_event(ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED), correction)
        self.assertEqual(correction.payload.applied_change, self.boundary.payload.applied_change)
        self.assertEqual(correction.payload.applied_at_ms, 1_788_450_000_000)
        self.assertEqual(note.payload, NoteRecordedPayload("The first timestamp used the start of the calendar day; this is the actual change time.", correction.record_id))
        with ExperimentStore(self.database_path) as reopened:
            self.assertEqual(reopened.replay(self.fixture.experiment.record_id), replayed)

    def test_api_appends_both_events_and_returns_full_history_with_effective_state(self) -> None:
        with TestClient(create_app(database_path=self.database_path)) as client:
            response = client.post(
                PS_MIN_BOUNDARY_CORRECTION_PATH,
                json={
                    "corrected_event_id": self.boundary.record_id,
                    "applied_at_ms": 1_788_450_000_000,
                    "note": "Corrected from my contemporaneous log.",
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["effective_boundary"]["applied_at_ms"], 1_788_450_000_000)
        self.assertEqual(len(payload["history"]), 7)
        original = next(event for event in payload["history"] if event["record_id"] == self.boundary.record_id)
        correction = payload["history"][-2]
        note = payload["history"][-1]
        self.assertFalse(original["effective"])
        self.assertTrue(correction["effective"])
        self.assertEqual(correction["correction_of_event_id"], self.boundary.record_id)
        self.assertEqual(note["event_type"], "note_recorded")
        self.assertEqual(note["note"], "Corrected from my contemporaneous log.")
        self.assertEqual(note["related_event_id"], correction["record_id"])

    def test_api_refuses_absent_or_stale_boundary_targets_without_appending(self) -> None:
        application = create_app(database_path=self.database_path)
        with TestClient(application) as client:
            stale = client.post(PS_MIN_BOUNDARY_CORRECTION_PATH, json={"corrected_event_id": "event:missing", "applied_at_ms": 1_788_450_000_000, "note": "Wrong target"})
            unchanged = client.get(PS_MIN_EXPERIMENT_HISTORY_PATH)

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(len(unchanged.json()["history"]), 5)

    def test_retained_fixture_exposes_history_but_does_not_invent_a_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "pap_pilot.sqlite3"
            with TestClient(create_app(database_path=database_path)) as client:
                history = client.get(PS_MIN_EXPERIMENT_HISTORY_PATH)
                rejected = client.post(PS_MIN_BOUNDARY_CORRECTION_PATH, json={"corrected_event_id": "event:invented", "applied_at_ms": 1_788_450_000_000, "note": "Must not append"})

        self.assertEqual(history.status_code, 200)
        self.assertFalse(history.json()["can_correct_boundary"])
        self.assertIsNone(history.json()["effective_boundary"])
        self.assertEqual(len(history.json()["history"]), 2)
        self.assertEqual(rejected.status_code, 409)

    def _append_original_boundary(self) -> ExperimentEvent:
        experiment = self.fixture.experiment
        change = self.fixture.known_change
        baseline_settings = (
            ExperimentSetting("epap", 10.0, "cm H₂O"),
            change.previous,
            ExperimentSetting("ps_max", 5.0, "cm H₂O"),
        )
        proposal = ExperimentProposal(
            problem_event_id=self.fixture.history[0].record_id,
            hypothesis_event_id=self.fixture.history[1].record_id,
            baseline_local_dates=("2026-08-28",),
            baseline_settings=baseline_settings,
            proposed_change=change,
            settings_held_fixed=(baseline_settings[0], baseline_settings[2]),
            evidence_record_ids=("night:synthetic", "session:synthetic", "signal:synthetic"),
            representative_intervals=(ExperimentEvidenceInterval("night:synthetic", "session:synthetic", 1_000, 2_000, ("night:synthetic", "session:synthetic", "signal:synthetic")),),
            expected_objective_effects=("Lower pressure support",),
            expected_subjective_effects=("Fewer awakenings",),
            minimum_valid_nights=1,
            invalid_night_criteria=("Missing signals",),
            possible_adverse_effects=("Discomfort",),
            stop_conditions=("Material worsening",),
            revert_conditions=("Sustained worsening",),
        )
        events = (
            self._event(3, "event:proposal", ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(proposal)),
            self._event(4, "event:accepted", ExperimentEventType.EXPERIMENT_ACCEPTED, ExperimentDecisionPayload("event:proposal", "Accepted")),
            self._event(5, "event:boundary-original", ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED, SettingChangeConfirmedPayload("event:accepted", change, 1_788_400_000_000)),
        )
        with ExperimentStore(self.database_path) as store:
            store.append_events(events)
        return events[-1]

    def _event(self, sequence: int, record_id: str, event_type: ExperimentEventType, payload) -> ExperimentEvent:
        return ExperimentEvent(
            record_id=record_id,
            experiment_record_id=self.fixture.experiment.record_id,
            sequence_number=sequence,
            event_type=event_type,
            recorded_at_ms=1_788_300_000_000 + sequence,
            recorded_by="user:local",
            payload=payload,
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=(self.fixture.experiment.record_id,),
            source_provenance_ids=("provenance:user",),
        )


if __name__ == "__main__":
    unittest.main()
