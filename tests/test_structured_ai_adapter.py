import unittest

from pap_pilot.engine import (
    AiMetricSummary,
    AiProviderUnavailable,
    AiTransmissionConsent,
    AiTransmissionNotAuthorized,
    AiWaveformExcerpt,
    StructuredAiContext,
    StructuredAiResponse,
    build_ai_payload,
    parse_ai_response,
    request_structured_advisory,
)


class StructuredAiAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = StructuredAiContext(
            "local experiment", "Evaluate one bounded hypothesis", (AiMetricSummary("metric:one", 1.25, "unit", "eligible"),),
            {"sleep_quality": 4, "morning_energy": None}, ("none_reported",),
            (AiWaveformExcerpt("flow_rate", "L/min", (0, 40, 80), (1.0, 2.0, 1.5)),), "engine:v1", ("rules:v1",),
        )
        self.consent = AiTransmissionConsent("openai", "responses", "approved-model", retention_acknowledged=True)

    def test_payload_is_bounded_and_redacted(self) -> None:
        payload = build_ai_payload(self.context)
        self.assertEqual(payload["experiment_label"], "experiment-1")
        self.assertNotIn("metric:source-secret", str(payload))
        self.assertNotIn("local experiment", str(payload))
        self.assertEqual(payload["waveform_excerpts"][0]["relative_times_ms"], [0, 40, 80])

    def test_valid_response_is_structured(self) -> None:
        response = parse_ai_response({"format": "pap-pilot.ai-advisory-response", "format_version": 1, "hypothesis": "A bounded hypothesis", "experiment": {"title": "Review one variable", "expected_objective_effects": ["Lower metric"], "expected_subjective_effects": ["Better sleep"], "limitations": ["Not causal"]}})
        self.assertIsInstance(response, StructuredAiResponse)
        self.assertEqual(response.experiment_title, "Review one variable")

    def test_malformed_response_and_unauthorized_or_unavailable_provider_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_ai_response({"format": "wrong", "format_version": 1})
        with self.assertRaises(AiTransmissionNotAuthorized):
            request_structured_advisory(self.context)
        with self.assertRaises(AiProviderUnavailable):
            request_structured_advisory(self.context, consent=self.consent)

    def test_injected_transport_is_only_used_after_consent(self) -> None:
        calls = []
        def transport(payload):
            calls.append(payload)
            return {"format": "pap-pilot.ai-advisory-response", "format_version": 1, "hypothesis": "A bounded hypothesis", "experiment": {"title": "Review one variable", "expected_objective_effects": ["Lower metric"], "expected_subjective_effects": ["Better sleep"], "limitations": ["Not causal"]}}
        result = request_structured_advisory(self.context, consent=self.consent, transport=transport)
        self.assertEqual(result.experiment_title, "Review one variable")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
