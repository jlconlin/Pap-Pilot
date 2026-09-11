"""Focused tests for generic experiment definitions, analysis, and safety dispatch."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from pap_pilot.engine import (
    GENERIC_EXPERIMENT_SCHEMA_ID,
    GENERIC_EXPERIMENT_SCHEMA_VERSION,
    PROSPECTIVE_SAFETY_POLICY_ID,
    PROSPECTIVE_SAFETY_POLICY_VERSION,
    ExperimentProposal,
    ExperimentEvidenceInterval,
    ExperimentSetting,
    ExperimentSettingChange,
    GenericExperimentAnalysisStatus,
    GenericExperimentChange,
    GenericExperimentDefinition,
    GenericExperimentError,
    GenericExperimentMetricObservation,
    GenericExperimentMetricSelection,
    GenericExperimentMetricStatus,
    GenericExperimentMode,
    GenericExperimentPeriod,
    GenericExperimentPeriodRole,
    GenericExperimentSafetyPolicy,
    GenericExperimentSafetyStatus,
    GenericExperimentVariableKind,
    ProspectiveNightEvidence,
    ProspectiveSafetyEvidence,
    PsMinSafetyPolicyInput,
    analyze_generic_experiment,
    dispatch_generic_experiment_safety,
    evaluate_prospective_safety,
)


class GenericExperimentTests(unittest.TestCase):
    """Prove that experiment analysis is no longer defined by PS Min."""

    def setUp(self) -> None:
        self.definition = self._mask_definition()

    def _mask_definition(self, *, metrics: tuple[GenericExperimentMetricSelection, ...] | None = None) -> GenericExperimentDefinition:
        selections = metrics or (
            GenericExperimentMetricSelection("mask_leak_fraction", "Time in large leak", "fraction", 2, ("metric-spec:mask-leak-fraction",)),
        )
        evidence = ("night:01", "night:02", "night:03", "night:04", "session:01", "session:03")
        return GenericExperimentDefinition(
            record_id="generic-experiment:mask-interface:v1",
            experiment_record_id="experiment:mask-interface",
            title="Mask interface comparison",
            mode=GenericExperimentMode.RETROSPECTIVE,
            problem="Determine whether mask interface choice changes attributable PAP evidence.",
            hypothesis="A nasal interface may have a different leak burden than a full-face interface.",
            competing_explanations=("Night-to-night variation", "Sleep-position changes"),
            change=GenericExperimentChange("mask_interface", "Mask interface", GenericExperimentVariableKind.EQUIPMENT, "full_face", "nasal"),
            periods=(
                GenericExperimentPeriod("full-face", "Full-face reference", GenericExperimentPeriodRole.REFERENCE, 0, ("night:01", "night:02"), ("night:01", "night:02")),
                GenericExperimentPeriod("nasal", "Nasal comparison", GenericExperimentPeriodRole.COMPARISON, 1, ("night:03", "night:04"), ("night:03", "night:04")),
            ),
            metric_selections=selections,
            evidence_record_ids=evidence,
            representative_intervals=(
                ExperimentEvidenceInterval("night:01", "session:01", 0, 60_000, ("night:01", "session:01")),
                ExperimentEvidenceInterval("night:03", "session:03", 120_000, 180_000, ("night:03", "session:03")),
            ),
            expected_objective_effects=("Different observed mask leak fraction",),
            expected_subjective_effects=("Different reported comfort",),
            safety_policy=None,
            invalid_night_criteria=("Required metric evidence is unavailable",),
            possible_adverse_effects=("Mask discomfort",),
            stop_conditions=("Stop the comparison if the interface cannot be used comfortably",),
            revert_conditions=("Return to the reference interface after material discomfort",),
            source_record_ids=("experiment:mask-interface", *evidence, *(value for selection in selections for value in selection.source_record_ids)),
            source_provenance_ids=("provenance:synthetic",),
            limitations=("Synthetic evidence proves contract behavior only.",),
        )

    def _observation(self, metric_id: str, night_id: str, value: float | None, *, unit: str = "fraction", reason: str = "") -> GenericExperimentMetricObservation:
        status = GenericExperimentMetricStatus.CALCULATED if value is not None else GenericExperimentMetricStatus.INSUFFICIENT_EVIDENCE
        return GenericExperimentMetricObservation(
            record_id=f"metric:{metric_id}:{night_id}",
            metric_id=metric_id,
            night_record_id=night_id,
            status=status,
            value=value,
            unit=unit,
            source_record_ids=(night_id, f"signal:{night_id}"),
            source_provenance_ids=("provenance:synthetic",),
            reason_codes=() if value is not None else (reason,),
        )

    def test_non_ps_min_experiment_is_represented_and_analyzed_descriptively(self) -> None:
        observations = (
            self._observation("mask_leak_fraction", "night:04", 0.08),
            self._observation("mask_leak_fraction", "night:01", 0.20),
            self._observation("mask_leak_fraction", "night:03", 0.12),
            self._observation("mask_leak_fraction", "night:02", 0.30),
        )

        result = analyze_generic_experiment(self.definition, observations)
        repeated = analyze_generic_experiment(self.definition, tuple(reversed(observations)))

        self.assertEqual(self.definition.schema_id, GENERIC_EXPERIMENT_SCHEMA_ID)
        self.assertEqual(self.definition.schema_version, GENERIC_EXPERIMENT_SCHEMA_VERSION)
        self.assertEqual(self.definition.change.kind, GenericExperimentVariableKind.EQUIPMENT)
        self.assertEqual(tuple(period.period_id for period in self.definition.periods), ("full-face", "nasal"))
        self.assertEqual(tuple(metric.metric_id for metric in self.definition.metric_selections), ("mask_leak_fraction",))
        self.assertEqual(result.status, GenericExperimentAnalysisStatus.ANALYZED)
        self.assertEqual(result.period_summaries[0].median, 0.25)
        self.assertEqual(result.period_summaries[1].median, 0.10)
        self.assertAlmostEqual(result.comparisons[0].comparison_minus_reference, -0.15)
        self.assertEqual(result.reason_codes, ())
        self.assertEqual(result, repeated)
        self.assertIn("no outcome threshold", result.limitations[1])

    def test_missing_metric_evidence_remains_explicit_and_can_make_analysis_partial(self) -> None:
        second = GenericExperimentMetricSelection("event_reference_rate", "Machine-labeled event reference rate", "events/hour", 2, ("metric-spec:event-reference-rate",))
        first = self.definition.metric_selections[0]
        definition = self._mask_definition(metrics=(first, second))
        observations = tuple(
            self._observation("mask_leak_fraction", night_id, None if night_id == "night:04" else value, reason="leak_signal_unavailable")
            for night_id, value in (("night:01", 0.20), ("night:02", 0.30), ("night:03", 0.12), ("night:04", 0.08))
        ) + tuple(
            self._observation("event_reference_rate", night_id, value, unit="events/hour")
            for night_id, value in (("night:01", 1.0), ("night:02", 2.0), ("night:03", 1.5), ("night:04", 1.0))
        )

        result = analyze_generic_experiment(definition, observations)

        self.assertEqual(result.status, GenericExperimentAnalysisStatus.PARTIAL)
        leak_comparison = next(value for value in result.comparisons if value.metric_id == "mask_leak_fraction")
        event_comparison = next(value for value in result.comparisons if value.metric_id == "event_reference_rate")
        self.assertEqual(leak_comparison.status, GenericExperimentMetricStatus.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(leak_comparison.comparison_minus_reference)
        self.assertIn("comparison:leak_signal_unavailable", leak_comparison.reason_codes)
        self.assertEqual(event_comparison.status, GenericExperimentMetricStatus.CALCULATED)
        self.assertIn("comparison:minimum_calculated_nights_not_met", result.reason_codes)

    def test_analysis_requires_explicit_complete_metric_night_ledger(self) -> None:
        observations = tuple(self._observation("mask_leak_fraction", night_id, 0.1) for night_id in ("night:01", "night:02", "night:03"))
        with self.assertRaisesRegex(GenericExperimentError, "Every selected metric and assigned night"):
            analyze_generic_experiment(self.definition, observations)

        with self.assertRaisesRegex(GenericExperimentError, "preselected metric"):
            analyze_generic_experiment(self.definition, (*observations, self._observation("unselected", "night:04", 1.0)))

    def test_definition_rejects_ambiguous_periods_and_is_immutable(self) -> None:
        duplicate_night = replace(self.definition.periods[1], night_record_ids=("night:02", "night:04"), source_record_ids=("night:02", "night:04"))
        with self.assertRaisesRegex(GenericExperimentError, "assigned night identifiers"):
            replace(self.definition, periods=(self.definition.periods[0], duplicate_night))
        with self.assertRaises(FrozenInstanceError):
            self.definition.title = "changed"  # type: ignore[misc]

    def test_one_reference_can_be_compared_with_multiple_named_periods(self) -> None:
        third = GenericExperimentPeriod("nasal-repeat", "Nasal repeat", GenericExperimentPeriodRole.COMPARISON, 2, ("night:05", "night:06"), ("night:05", "night:06"))
        definition = replace(
            self.definition,
            periods=(*self.definition.periods, third),
            evidence_record_ids=(*self.definition.evidence_record_ids, "night:05", "night:06"),
            source_record_ids=(*self.definition.source_record_ids, "night:05", "night:06"),
        )
        observations = tuple(self._observation("mask_leak_fraction", night_id, value) for night_id, value in (("night:01", 0.20), ("night:02", 0.30), ("night:03", 0.12), ("night:04", 0.08), ("night:05", 0.10), ("night:06", 0.14)))

        result = analyze_generic_experiment(definition, observations)

        self.assertEqual(tuple(value.comparison_period_id for value in result.comparisons), ("nasal", "nasal-repeat"))
        self.assertAlmostEqual(result.comparisons[0].comparison_minus_reference, -0.15)
        self.assertAlmostEqual(result.comparisons[1].comparison_minus_reference, -0.13)

    def test_generic_contract_has_no_adapter_api_ui_ai_or_persistence_dependency(self) -> None:
        source = (Path(__file__).parents[1] / "src/pap_pilot/engine/experiments/generic.py").read_text(encoding="utf-8")
        for forbidden in ("pap_pilot.adapter", "pap_pilot.api", "pap_pilot.ui", "pap_pilot.engine.ai", "sqlite3"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_retrospective_safety_is_not_applicable_not_approved(self) -> None:
        result = dispatch_generic_experiment_safety(self.definition)
        self.assertEqual(result.status, GenericExperimentSafetyStatus.NOT_APPLICABLE)
        self.assertIsNone(result.policy_id)
        self.assertEqual(result.failure_codes, ("retrospective_analysis_has_no_prospective_action",))


class GenericSafetyDispatchTests(unittest.TestCase):
    """Keep generic routing fail-closed around the unchanged PS Min policy."""

    def setUp(self) -> None:
        self.settings = (
            ExperimentSetting("therapy_mode_code", 6),
            ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"),
            ExperimentSetting("ps_min", 2.0, "cm H₂O"),
            ExperimentSetting("ps_max", 5.0, "cm H₂O"),
            ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        self.proposal = ExperimentProposal(
            "event:problem",
            "event:hypothesis",
            ("2026-01-01",),
            self.settings,
            ExperimentSettingChange(self.settings[3], ExperimentSetting("ps_min", 1.0, "cm H₂O")),
            self.settings[:3] + self.settings[4:],
            ("night:reference", "session:reference"),
            (ExperimentEvidenceInterval("night:reference", "session:reference", 0, 60_000, ("night:reference", "session:reference")),),
            ("Lower pressure exposure",),
            ("Improved sleep",),
            3,
            ("Insufficient evidence",),
            ("Reduced support",),
            ("Stop on material worsening",),
            ("Restore the complete reference settings",),
        )
        nights = tuple(ProspectiveNightEvidence(f"2026-01-0{index}", 300_000) for index in range(1, 4))
        self.evidence = ProspectiveSafetyEvidence(nights, nights, self.settings)
        self.definition = self._definition(
            GenericExperimentChange("ps_min", "Minimum pressure support", GenericExperimentVariableKind.DEVICE_SETTING, 2.0, 1.0, "cm H₂O"),
            GenericExperimentSafetyPolicy(PROSPECTIVE_SAFETY_POLICY_ID, PROSPECTIVE_SAFETY_POLICY_VERSION),
        )

    def _definition(self, change: GenericExperimentChange, policy: GenericExperimentSafetyPolicy) -> GenericExperimentDefinition:
        return GenericExperimentDefinition(
            record_id="generic-experiment:prospective:v1",
            experiment_record_id="experiment:prospective",
            title="Prospective experiment",
            mode=GenericExperimentMode.PROSPECTIVE,
            problem="Test a bounded prospective hypothesis.",
            hypothesis="The selected variable may alter a preselected PAP metric.",
            competing_explanations=("Normal variation",),
            change=change,
            periods=(
                GenericExperimentPeriod("reference", "Reference", GenericExperimentPeriodRole.REFERENCE, 0, ("night:reference",), ("night:reference",)),
                GenericExperimentPeriod("comparison", "Comparison", GenericExperimentPeriodRole.COMPARISON, 1, ("night:comparison",), ("night:comparison",)),
            ),
            metric_selections=(GenericExperimentMetricSelection("minute_ventilation_upper_tail_ratio", "Ventilation dispersion", None, 1, ("metric-spec:ventilation",)),),
            evidence_record_ids=("night:comparison", "night:reference", "session:comparison", "session:reference"),
            representative_intervals=(
                ExperimentEvidenceInterval("night:reference", "session:reference", 0, 60_000, ("night:reference", "session:reference")),
                ExperimentEvidenceInterval("night:comparison", "session:comparison", 60_000, 120_000, ("night:comparison", "session:comparison")),
            ),
            expected_objective_effects=("Different ventilation dispersion",),
            expected_subjective_effects=("Different reported sleep experience",),
            safety_policy=policy,
            invalid_night_criteria=("Insufficient evidence",),
            possible_adverse_effects=("Worsening",),
            stop_conditions=("Stop on material worsening",),
            revert_conditions=("Restore the reference state",),
            source_record_ids=("experiment:prospective", "metric-spec:ventilation", "night:comparison", "night:reference", "session:comparison", "session:reference"),
            source_provenance_ids=("provenance:synthetic",),
            limitations=("Synthetic policy-dispatch fixture only.",),
        )

    def test_registered_ps_min_policy_delegates_without_changing_old_result(self) -> None:
        legacy = evaluate_prospective_safety(self.proposal, self.evidence)
        dispatched = dispatch_generic_experiment_safety(self.definition, PsMinSafetyPolicyInput(self.proposal, self.evidence))

        self.assertTrue(legacy.eligible)
        self.assertEqual(dispatched.status, GenericExperimentSafetyStatus.ELIGIBLE)
        self.assertEqual((dispatched.policy_id, dispatched.policy_version), (legacy.policy_id, legacy.policy_version))
        self.assertEqual(dispatched.failure_codes, tuple(code.value for code in legacy.failure_codes))
        self.assertEqual(dispatched.delegated_engine_version, legacy.engine_version)

    def test_ps_min_policy_rejection_and_input_mismatch_fail_closed(self) -> None:
        unsafe_proposal = replace(self.proposal, proposed_change=ExperimentSettingChange(self.settings[3], ExperimentSetting("ps_min", 1.5, "cm H₂O")))
        unsafe_definition = replace(self.definition, change=replace(self.definition.change, comparison_value=1.5))
        delegated = dispatch_generic_experiment_safety(unsafe_definition, PsMinSafetyPolicyInput(unsafe_proposal, self.evidence))
        mismatch = dispatch_generic_experiment_safety(self.definition, PsMinSafetyPolicyInput(unsafe_proposal, self.evidence))

        self.assertEqual(delegated.status, GenericExperimentSafetyStatus.INELIGIBLE)
        self.assertIn("unsupported_scope", delegated.failure_codes)
        self.assertEqual(mismatch.status, GenericExperimentSafetyStatus.INELIGIBLE)
        self.assertEqual(mismatch.failure_codes, ("policy_input_mismatch",))

    def test_non_ps_min_prospective_definition_does_not_expand_allowlist(self) -> None:
        non_ps_change = GenericExperimentChange("mask_interface", "Mask interface", GenericExperimentVariableKind.EQUIPMENT, "full_face", "nasal")
        unregistered = self._definition(non_ps_change, GenericExperimentSafetyPolicy("pap-pilot.future-mask-policy", 1))
        unavailable = dispatch_generic_experiment_safety(unregistered)
        misrouted = dispatch_generic_experiment_safety(replace(unregistered, safety_policy=GenericExperimentSafetyPolicy(PROSPECTIVE_SAFETY_POLICY_ID, PROSPECTIVE_SAFETY_POLICY_VERSION)), PsMinSafetyPolicyInput(self.proposal, self.evidence))

        self.assertEqual(unavailable.status, GenericExperimentSafetyStatus.POLICY_UNAVAILABLE)
        self.assertEqual(unavailable.failure_codes, ("unsupported_safety_policy",))
        self.assertEqual(misrouted.status, GenericExperimentSafetyStatus.INELIGIBLE)
        self.assertEqual(misrouted.failure_codes, ("policy_input_mismatch",))

    def test_registered_policy_requires_typed_input(self) -> None:
        result = dispatch_generic_experiment_safety(self.definition)
        self.assertEqual(result.status, GenericExperimentSafetyStatus.INELIGIBLE)
        self.assertEqual(result.failure_codes, ("missing_ps_min_policy_input",))


if __name__ == "__main__":
    unittest.main()
