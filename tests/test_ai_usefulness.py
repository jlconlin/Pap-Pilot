from pathlib import Path
import unittest

from pap_pilot.engine import (
    AiProviderUnavailable,
    AiMetricSummary,
    AiTransmissionConsent,
    AiTransmissionNotAuthorized,
    StructuredAiContext,
    StructuredAiResponse,
    build_ps_min_retrospective_evidence_report,
    request_structured_advisory,
    reconstruct_ps_min_experiment_fixture,
)


class AiUsefulnessEvaluationTests(unittest.TestCase):
    def test_evaluation_records_defer_revision_and_all_required_cases(self) -> None:
        text = (Path(__file__).parents[1] / "docs" / "validation" / "ai-usefulness-s48.md").read_text(encoding="utf-8")
        for phrase in ("Revise and defer", "not_evaluable_without_fabrication", "non-viable regardless of wording", "hosted_transmission_not_authorized", "Recommendation scope is not expanded"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_deterministic_fixture_and_fail_closed_states_are_reproducible(self) -> None:
        fixture = reconstruct_ps_min_experiment_fixture()
        report = build_ps_min_retrospective_evidence_report()
        self.assertEqual(fixture.evaluation.status.value, "not_evaluable_without_fabrication")
        self.assertEqual(report.evaluation_status.value, "not_evaluable_without_fabrication")
        response = StructuredAiResponse("A bounded hypothesis", "Explain only", ("Possible effect",), ("Possible outcome",), ("No causal claim",))
        context = StructuredAiContext("experiment-1", "A bounded hypothesis", (AiMetricSummary("metric", None, "unit", "missing"),), {"sleep_quality": None}, ("not_reported",), (), "engine:v1", ("rules:v1",))
        with self.assertRaises(AiTransmissionNotAuthorized):
            request_structured_advisory(context)
        with self.assertRaises(AiProviderUnavailable):
            request_structured_advisory(context, consent=AiTransmissionConsent("openai", "responses", "model", retention_acknowledged=True))
        self.assertEqual(response.experiment_title, "Explain only")


if __name__ == "__main__":
    unittest.main()
