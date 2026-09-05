from pathlib import Path
import unittest


class ProspectiveSafetyPolicyDocumentTests(unittest.TestCase):
    def test_policy_resolves_required_rules(self) -> None:
        path = Path(__file__).parents[1] / "docs" / "decisions" / "0009-prospective-safety-policy.md"
        text = path.read_text(encoding="utf-8")
        required = (
            "**Status:** Accepted", "**Version:** 1", "PS Min 2.0 to 1.0", "therapy_mode_code=6",
            "loader_mode_code=7", "at least three included nights", "300,000 ms", "Stop and escalation rules",
            "Reversion requirements", "never writes OSCAR", "cannot bypass a failed gate",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_policy_is_explicitly_single_variable_and_manual(self) -> None:
        text = (Path(__file__).parents[1] / "docs" / "decisions" / "0009-prospective-safety-policy.md").read_text(encoding="utf-8")
        self.assertIn("One proposal changes one variable once", text)
        self.assertIn("manually restores that snapshot", text)
        self.assertIn("no automatic stop or device action", text)


if __name__ == "__main__":
    unittest.main()
