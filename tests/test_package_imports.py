"""Smoke tests for the package scaffold."""

from importlib import import_module
import unittest


class PackageImportTests(unittest.TestCase):
    """Verify that the intended package boundaries are importable."""

    def test_package_boundaries_import(self) -> None:
        for module_name in (
            "pap_pilot",
            "pap_pilot.adapter",
            "pap_pilot.adapter.cohort",
            "pap_pilot.api",
            "pap_pilot.api.server",
            "pap_pilot.engine",
            "pap_pilot.engine.analysis",
            "pap_pilot.engine.analysis.model",
            "pap_pilot.engine.experiments",
            "pap_pilot.engine.experiments.classification",
            "pap_pilot.engine.experiments.generic",
            "pap_pilot.engine.experiments.retrospective_fixture",
            "pap_pilot.engine.experiments.retrospective_evidence",
            "pap_pilot.engine.experiments.retrospective_evaluation",
            "pap_pilot.engine.experiments.retrospective_protocol",
            "pap_pilot.engine.metrics",
            "pap_pilot.engine.model",
            "pap_pilot.engine.quality",
            "pap_pilot.engine.reports",
            "pap_pilot.engine.reports.retrospective",
            "pap_pilot.ui",
            "pap_pilot.workflow",
            "pap_pilot.workflow.analysis",
            "pap_pilot.workflow.local_workspace",
            "pap_pilot.workflow.retrospective",
        ):
            with self.subTest(module_name=module_name):
                module = import_module(module_name)
                self.assertEqual(module.__name__, module_name)


if __name__ == "__main__":
    unittest.main()
