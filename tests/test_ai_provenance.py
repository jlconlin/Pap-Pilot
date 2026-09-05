from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pap_pilot.engine import (
    AiProvenancePayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentRecord,
    ExperimentStore,
    ProblemRecordedPayload,
    SourceClass,
    build_ai_provenance_event,
)


class AiProvenanceTests(unittest.TestCase):
    def test_provenance_is_append_only_and_reconstructs_complete_chain(self) -> None:
        experiment = ExperimentRecord("experiment:ai", "AI advisory", 1, "user:local", ("source:ai",))
        problem = ExperimentEvent("event:problem", experiment.record_id, 1, ExperimentEventType.PROBLEM_RECORDED, 1, "user:local", ProblemRecordedPayload("Review evidence"), SourceClass.USER_REPORTED, (experiment.record_id,), ("source:ai",))
        provenance = build_ai_provenance_event(
            experiment_record_id=experiment.record_id, related_event_id=problem.record_id, event_record_id="event:ai-provenance", sequence_number=2, recorded_at_ms=2,
            provider="openai", model="approved-model", prompt_version="prompt:v1", approved_input_record_ids=("input:summary",), raw_structured_output={"format": "pap-pilot.ai-advisory-response", "format_version": 1, "hypothesis": "A bounded hypothesis"}, evidence_record_ids=("evidence:one",), consent_record_id="consent:one",
        )
        self.assertIsInstance(provenance.payload, AiProvenancePayload)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pap_pilot.sqlite3"
            with ExperimentStore(path) as store:
                store.create_experiment(experiment)
                store.append_event(problem)
                store.append_ai_provenance(provenance)
                replayed = store.replay(experiment.record_id)
                self.assertEqual(replayed.history[-1].payload.raw_structured_output["hypothesis"], "A bounded hypothesis")
                with self.assertRaises(Exception):
                    store.append_event(provenance)

    def test_credentials_are_rejected_from_provenance(self) -> None:
        with self.assertRaises(ValueError):
            AiProvenancePayload("note", "event:one", "openai", "model", "prompt", ("input",), {"api_key": "secret"}, ("evidence",), "consent")


if __name__ == "__main__":
    unittest.main()
