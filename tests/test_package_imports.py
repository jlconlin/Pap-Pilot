"""Smoke tests for the package scaffold."""

from importlib import import_module
import unittest


class PackageImportTests(unittest.TestCase):
    """Verify that the intended package boundaries are importable."""

    def test_package_boundaries_import(self) -> None:
        for module_name in (
            "pap_pilot",
            "pap_pilot.adapter",
            "pap_pilot.engine",
            "pap_pilot.engine.model",
            "pap_pilot.engine.quality",
        ):
            with self.subTest(module_name=module_name):
                module = import_module(module_name)
                self.assertEqual(module.__name__, module_name)


if __name__ == "__main__":
    unittest.main()
