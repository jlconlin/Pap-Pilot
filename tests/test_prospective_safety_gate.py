from dataclasses import replace
import unittest

from pap_pilot.engine import (
    ExperimentEvidenceInterval,
    ExperimentProposal,
    ExperimentSetting,
    ExperimentSettingChange,
    ProspectiveNightEvidence,
    ProspectiveSafetyEvidence,
    ProspectiveSafetyFailureCode,
    evaluate_prospective_safety,
)


class ProspectiveSafetyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = (
            ExperimentSetting("therapy_mode_code", 6), ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"), ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_max", 5.0, "cm H₂O"), ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        self.proposal = ExperimentProposal(
            "problem", "hypothesis", ("2026-01-01",), self.baseline,
            ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 1.0, "cm H₂O")),
            tuple(setting for setting in self.baseline if setting.name != "ps_min"), ("night", "session"),
            (ExperimentEvidenceInterval("night", "session", 1, 2, ("night", "session")),),
            ("objective",), ("subjective",), 3, ("invalid",), ("adverse",), ("stop",), ("revert",),
        )
        nights = tuple(ProspectiveNightEvidence(f"2026-01-0{index}", 300_000) for index in range(1, 4))
        self.evidence = ProspectiveSafetyEvidence(nights, nights, self.baseline)

    def test_valid_exact_scope_is_eligible(self) -> None:
        result = evaluate_prospective_safety(self.proposal, self.evidence)
        self.assertTrue(result.eligible)
        self.assertEqual(result.failure_codes, ())

    def test_unsupported_scope_and_multi_variable_shape_are_rejected(self) -> None:
        changed = replace(self.proposal, proposed_change=ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 1.5, "cm H₂O")))
        result = evaluate_prospective_safety(changed, self.evidence)
        self.assertIn(ProspectiveSafetyFailureCode.UNSUPPORTED_SCOPE, result.failure_codes)
        malformed = replace(self.proposal, settings_held_fixed=self.proposal.settings_held_fixed[:-1])
        self.assertIn(ProspectiveSafetyFailureCode.MULTI_VARIABLE_CHANGE, evaluate_prospective_safety(malformed, self.evidence).failure_codes)

    def test_insufficient_data_is_structured_per_arm(self) -> None:
        short = replace(self.evidence, baseline_nights=self.evidence.baseline_nights[:2], intervention_nights=(ProspectiveNightEvidence("2026-01-01", 299_999),) * 3)
        result = evaluate_prospective_safety(self.proposal, short)
        self.assertEqual(set(result.failure_codes), {ProspectiveSafetyFailureCode.INSUFFICIENT_BASELINE_DATA, ProspectiveSafetyFailureCode.INSUFFICIENT_INTERVENTION_DATA})

    def test_missing_reversion_and_unsupported_evidence_are_rejected(self) -> None:
        evidence = replace(self.evidence, reversion_settings=None, source_supported=False, time_boundaries_resolved=False)
        result = evaluate_prospective_safety(self.proposal, evidence)
        self.assertEqual(set(result.failure_codes), {ProspectiveSafetyFailureCode.MISSING_REVERSION, ProspectiveSafetyFailureCode.UNSUPPORTED_DATA_SOURCE, ProspectiveSafetyFailureCode.UNRESOLVED_TIME_BOUNDARY})


if __name__ == "__main__":
    unittest.main()
