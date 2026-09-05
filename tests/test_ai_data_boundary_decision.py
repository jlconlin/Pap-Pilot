from pathlib import Path
import unittest


class AiDataBoundaryDecisionTests(unittest.TestCase):
    def test_decision_defers_transmission_and_covers_required_controls(self) -> None:
        text = (Path(__file__).parents[1] / "docs" / "decisions" / "0010-ai-data-boundary-and-provider.md").read_text(encoding="utf-8")
        for phrase in (
            "OpenAI's Responses API", "hosted health-data transmission is authorized", "Permitted payload",
            "Redaction and minimization", "Credential and local-retention requirements", "hosted_transmission_not_authorized",
            "raw OSCAR databases/files", "original free-text journal notes", "new decision version",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_decision_is_explicitly_no_network_calls_until_consent(self) -> None:
        text = (Path(__file__).parents[1] / "docs" / "decisions" / "0010-ai-data-boundary-and-provider.md").read_text(encoding="utf-8")
        self.assertIn("without making a network request", text)
        self.assertIn("No provider call, credential", text)
        self.assertIn("AI never reads OSCAR", text)


if __name__ == "__main__":
    unittest.main()
