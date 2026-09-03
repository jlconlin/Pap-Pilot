"""Table-driven tests for deterministic retrospective outcome classification."""

from dataclasses import FrozenInstanceError, replace
import unittest

from pap_pilot.engine import (
    MEAN_MASK_PRESSURE_ABOVE_EPAP_ALGORITHM_VERSION,
    MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION,
    OUTCOME_CLASSIFICATION_RULE_SET_ID,
    OUTCOME_CLASSIFICATION_RULE_SET_VERSION,
    AllocationInterval,
    ConfounderEvidenceStatus,
    ConfounderKind,
    ConfounderReportStatus,
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentNightAllocation,
    ExperimentPeriod,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentRevisedPayload,
    ExperimentSetting,
    ExperimentSettingChange,
    MetricId,
    MetricInterval,
    MetricReason,
    MetricResult,
    MetricSettingValue,
    MetricStatus,
    MetricValue,
    NightAllocation,
    NightAllocationStatus,
    ObservationRecordedPayload,
    OutcomeAction,
    OutcomeClassification,
    OutcomeClassificationError,
    OutcomeId,
    OutcomeState,
    SettingChangeConfirmedPayload,
    SleepJournalConfounder,
    SleepJournalEntry,
    SleepJournalEntryRecordedPayload,
    SourceClass,
    SubjectiveDomainState,
    evaluate_outcome_classification,
)


class OutcomeClassificationTests(unittest.TestCase):
    """Verify all version-1 states, precedence rules, actions, and gates."""

    def test_every_classification_and_action_mapping(self) -> None:
        cases = (
            ("clear", [2.5] * 3, [1.2] * 3, {"sleep_quality": [4] * 3, "morning_energy": [4] * 3}, OutcomeClassification.CLEAR_IMPROVEMENT, OutcomeAction.KEEP),
            ("probable improvement", [2.5] * 3, [1.1] * 3, {}, OutcomeClassification.PROBABLE_IMPROVEMENT, OutcomeAction.KEEP),
            ("objective tradeoff", [2.5] * 3, [1.3] * 3, {"sleep_quality": [4] * 3, "morning_energy": [4] * 3}, OutcomeClassification.MIXED_TRADEOFF, OutcomeAction.INCONCLUSIVE),
            ("subjective tradeoff", [3.0] * 3, [1.2] * 3, {"sleep_quality": [4] * 3, "morning_energy": [2] * 3}, OutcomeClassification.MIXED_TRADEOFF, OutcomeAction.INCONCLUSIVE),
            ("no change", [3.0] * 3, [1.2] * 3, {}, OutcomeClassification.NO_MEANINGFUL_CHANGE, OutcomeAction.REVERT),
            ("worsening", [3.5] * 3, [1.2] * 3, {"sleep_quality": [2] * 3, "morning_energy": [2] * 3}, OutcomeClassification.PROBABLE_WORSENING, OutcomeAction.REVERT),
            ("unsupported single signal", [2.5] * 3, [1.2] * 3, {}, OutcomeClassification.INCONCLUSIVE, OutcomeAction.INCONCLUSIVE),
        )
        for name, pressure, ventilation, journal, classification, action in cases:
            with self.subTest(name=name):
                result = self._evaluate(pressure_intervention=pressure, ventilation_intervention=ventilation, intervention_journal=journal)
                self.assertEqual((result.classification, result.action), (classification, action))

    def test_inclusive_thresholds_and_neutral_inner_boundaries(self) -> None:
        cases = (
            (OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP, {"pressure_intervention": [2.5] * 3}, OutcomeState.EXPECTED_MECHANISM),
            (OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP, {"pressure_intervention": [2.500001] * 3}, OutcomeState.NEUTRAL),
            (OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP, {"pressure_intervention": [3.499999] * 3}, OutcomeState.NEUTRAL),
            (OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP, {"pressure_intervention": [3.5] * 3}, OutcomeState.UNEXPECTED_MECHANISM),
            (OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, {"ventilation_intervention": [1.1] * 3}, OutcomeState.FAVORABLE),
            (OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, {"ventilation_intervention": [1.100001] * 3}, OutcomeState.NEUTRAL),
            (OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, {"ventilation_intervention": [1.299999] * 3}, OutcomeState.NEUTRAL),
            (OutcomeId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, {"ventilation_intervention": [1.3] * 3}, OutcomeState.ADVERSE),
            (OutcomeId.AWAKENINGS_COUNT, {"intervention_journal": {"awakenings_count": [1] * 3}}, OutcomeState.FAVORABLE),
            (OutcomeId.AWAKENINGS_COUNT, {"intervention_journal": {"awakenings_count": [2] * 3}}, OutcomeState.NEUTRAL),
            (OutcomeId.AWAKENINGS_COUNT, {"intervention_journal": {"awakenings_count": [3] * 3}}, OutcomeState.ADVERSE),
            (OutcomeId.SLEEP_QUALITY, {"intervention_journal": {"sleep_quality": [4] * 3}}, OutcomeState.FAVORABLE),
            (OutcomeId.SLEEP_QUALITY, {"intervention_journal": {"sleep_quality": [3] * 3}}, OutcomeState.NEUTRAL),
            (OutcomeId.SLEEP_QUALITY, {"intervention_journal": {"sleep_quality": [2] * 3}}, OutcomeState.ADVERSE),
            (OutcomeId.MORNING_ENERGY, {"intervention_journal": {"morning_energy": [4] * 3}}, OutcomeState.FAVORABLE),
            (OutcomeId.MORNING_ENERGY, {"intervention_journal": {"morning_energy": [3] * 3}}, OutcomeState.NEUTRAL),
            (OutcomeId.MORNING_ENERGY, {"intervention_journal": {"morning_energy": [2] * 3}}, OutcomeState.ADVERSE),
            (OutcomeId.DAYTIME_TIREDNESS, {"intervention_journal": {"daytime_tiredness": [2] * 3}}, OutcomeState.FAVORABLE),
            (OutcomeId.DAYTIME_TIREDNESS, {"intervention_journal": {"daytime_tiredness": [3] * 3}}, OutcomeState.NEUTRAL),
            (OutcomeId.DAYTIME_TIREDNESS, {"intervention_journal": {"daytime_tiredness": [4] * 3}}, OutcomeState.ADVERSE),
        )
        for outcome_id, arguments, expected in cases:
            with self.subTest(outcome=outcome_id.value, expected=expected.value):
                self.assertEqual(self._evaluate(**arguments).outcome(outcome_id).state, expected)

    def test_direction_consistency_uses_exact_two_thirds_rule(self) -> None:
        exact = self._evaluate(pressure_intervention=[2.5, 2.5, 3.0])
        pressure = exact.outcome(OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP)
        self.assertEqual((pressure.state, pressure.direction_matching_count, pressure.direction_total_count), (OutcomeState.EXPECTED_MECHANISM, 2, 3))

        unstable = self._evaluate(
            pressure_intervention=[3.0] * 4,
            ventilation_intervention=[1.2] * 4,
            intervention_journal={"sleep_quality": [3, 3, 5, 5], "morning_energy": [3] * 4, "awakenings_count": [2] * 4, "daytime_tiredness": [3] * 4},
        )
        sleep_quality = unstable.outcome(OutcomeId.SLEEP_QUALITY)
        self.assertEqual((sleep_quality.delta, sleep_quality.direction_matching_count, sleep_quality.direction_total_count), (1.0, 2, 4))
        self.assertEqual((sleep_quality.state, unstable.subjective_domain_state), (OutcomeState.UNSTABLE, SubjectiveDomainState.UNSTABLE))
        self.assertEqual((unstable.classification, unstable.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.EXTEND))

    def test_subjective_domain_aggregation_states(self) -> None:
        cases = (
            ({"sleep_quality": [4] * 3, "morning_energy": [4] * 3}, SubjectiveDomainState.FAVORABLE),
            ({"sleep_quality": [2] * 3, "morning_energy": [2] * 3}, SubjectiveDomainState.ADVERSE),
            ({"sleep_quality": [4] * 3, "morning_energy": [2] * 3}, SubjectiveDomainState.MIXED),
            ({}, SubjectiveDomainState.NEUTRAL),
            ({"sleep_quality": [4] * 3}, SubjectiveDomainState.WEAK_FAVORABLE),
            ({"sleep_quality": [2] * 3}, SubjectiveDomainState.WEAK_ADVERSE),
        )
        for journal, expected in cases:
            with self.subTest(expected=expected.value):
                self.assertEqual(self._evaluate(intervention_journal=journal).subjective_domain_state, expected)

    def test_confounder_boundaries_and_directional_downgrades(self) -> None:
        clear_arguments = {"pressure_intervention": [2.5] * 3, "intervention_journal": {"sleep_quality": [4] * 3, "morning_energy": [4] * 3}}
        exact_imbalance = self._evaluate(**clear_arguments, intervention_confounder_statuses=[ConfounderReportStatus.REPORTED, ConfounderReportStatus.NONE_REPORTED, ConfounderReportStatus.NONE_REPORTED])
        self.assertEqual(exact_imbalance.confounders.status, ConfounderEvidenceStatus.IMBALANCED)
        self.assertEqual((exact_imbalance.classification, exact_imbalance.action), (OutcomeClassification.PROBABLE_IMPROVEMENT, OutcomeAction.KEEP))
        self.assertIn("confounder_imbalance_clear_downgrade", exact_imbalance.reason_codes)

        directional = self._evaluate(
            pressure_intervention=[2.5] * 3,
            ventilation_intervention=[1.1] * 3,
            intervention_confounder_statuses=[ConfounderReportStatus.REPORTED, ConfounderReportStatus.NONE_REPORTED, ConfounderReportStatus.NONE_REPORTED],
        )
        self.assertEqual((directional.classification, directional.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.INCONCLUSIVE))

        exact_reporting_boundary = self._evaluate(baseline_confounder_statuses=[ConfounderReportStatus.NOT_REPORTED, ConfounderReportStatus.NONE_REPORTED, ConfounderReportStatus.NONE_REPORTED])
        self.assertEqual(exact_reporting_boundary.confounders.status, ConfounderEvidenceStatus.BALANCED)
        insufficient = self._evaluate(baseline_confounder_statuses=[ConfounderReportStatus.NOT_REPORTED, ConfounderReportStatus.NOT_REPORTED, ConfounderReportStatus.NONE_REPORTED])
        self.assertEqual(insufficient.confounders.status, ConfounderEvidenceStatus.INSUFFICIENT_REPORTING)
        self.assertEqual((insufficient.classification, insufficient.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.INCONCLUSIVE))

        arguments = list(self._build_inputs(**clear_arguments))
        arguments[6] = (*arguments[6], self._event("event:confounder", 100, ExperimentEventType.CONFOUNDER_RECORDED, ObservationRecordedPayload("Synthetic travel", 20_000, "night:i:0")))
        standalone_event = evaluate_outcome_classification(*arguments)
        self.assertEqual(standalone_event.confounders.intervention.confounded_night_count, 1)
        self.assertIn("event:confounder", standalone_event.source_record_ids)

    def test_adverse_effect_precedence(self) -> None:
        mixed = self._evaluate(pressure_intervention=[2.5] * 3, adverse_effect=True)
        self.assertEqual((mixed.classification, mixed.action), (OutcomeClassification.MIXED_TRADEOFF, OutcomeAction.INCONCLUSIVE))
        self.assertEqual(mixed.adverse_effect_event_ids, ("event:adverse",))

        worsening = self._evaluate(adverse_effect=True)
        self.assertEqual((worsening.classification, worsening.action), (OutcomeClassification.PROBABLE_WORSENING, OutcomeAction.REVERT))

        insufficient = self._evaluate(pressure_baseline=[3.0] * 2, adverse_effect=True)
        self.assertEqual((insufficient.classification, insufficient.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.INCONCLUSIVE))

    def test_every_insufficient_evidence_action_path(self) -> None:
        cases = (
            ("too few nights", {"pressure_baseline": [3.0] * 2}, "insufficient_baseline_nights", OutcomeAction.EXTEND),
            ("missing objective result", {"ventilation_intervention": [1.2] * 2, "intervention_count": 3}, "too_few_calculated_minute_ventilation_upper_tail_ratio_intervention", OutcomeAction.EXTEND),
            ("too few subjective outcomes", {"baseline_journal": {"awakenings_count": [2] * 3, "sleep_quality": [None] * 3, "morning_energy": [None] * 3, "daytime_tiredness": [None] * 3}, "intervention_journal": {"awakenings_count": [2] * 3, "sleep_quality": [None] * 3, "morning_energy": [None] * 3, "daytime_tiredness": [None] * 3}}, "too_few_subjective_outcomes", OutcomeAction.EXTEND),
            ("missing anchor", {"baseline_journal": {"sleep_quality": [None] * 3, "morning_energy": [None] * 3}, "intervention_journal": {"sleep_quality": [None] * 3, "morning_energy": [None] * 3}}, "subjective_anchor_missing", OutcomeAction.EXTEND),
        )
        for name, arguments, reason, action in cases:
            with self.subTest(name=name):
                result = self._evaluate(**arguments)
                self.assertEqual(result.classification, OutcomeClassification.INCONCLUSIVE)
                self.assertEqual(result.action, action)
                self.assertIn(reason, result.reason_codes)

        raised_minimum = self._evaluate(minimum_valid_nights=4)
        self.assertEqual(raised_minimum.required_nights_per_arm, 4)
        self.assertEqual((raised_minimum.classification, raised_minimum.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.EXTEND))

    def test_input_linkage_failures_are_inconclusive_not_silently_ignored(self) -> None:
        arguments = list(self._build_inputs())
        acceptance = arguments[1]
        arguments[1] = replace(acceptance, payload=ExperimentDecisionPayload("event:wrong-proposal", "Accepted for test"))
        result = evaluate_outcome_classification(*arguments)
        self.assertEqual((result.classification, result.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.INCONCLUSIVE))
        self.assertIn("proposal_acceptance_linkage_mismatch", result.reason_codes)

        arguments = list(self._build_inputs())
        arguments[4] = (*arguments[4], replace(arguments[4][0], record_id="metric:duplicate"))
        duplicate = evaluate_outcome_classification(*arguments)
        self.assertIn("duplicate_metric_result", duplicate.reason_codes)
        self.assertEqual(duplicate.action, OutcomeAction.INCONCLUSIVE)

        arguments = list(self._build_inputs())
        proposal_event = arguments[0]
        proposal = proposal_event.payload.proposal
        unsupported_baseline = tuple(ExperimentSetting(value.name, 5 if value.name == "therapy_mode_code" else value.value, value.unit) for value in proposal.baseline_settings)
        unsupported_held = tuple(value for value in unsupported_baseline if value.name != "ps_min")
        arguments[0] = replace(proposal_event, payload=ExperimentProposedPayload(replace(proposal, baseline_settings=unsupported_baseline, settings_held_fixed=unsupported_held)))
        unsupported = evaluate_outcome_classification(*arguments)
        self.assertIn("unsupported_experiment_scope", unsupported.reason_codes)
        self.assertEqual((unsupported.classification, unsupported.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.INCONCLUSIVE))

        arguments = list(self._build_inputs())
        unknown_metric = replace(arguments[4][0], record_id="metric:unknown-night", night_record_id="night:unknown")
        arguments[4] = (unknown_metric, *arguments[4][1:])
        unknown = evaluate_outcome_classification(*arguments)
        self.assertIn("metric_night_not_allocated", unknown.reason_codes)
        self.assertEqual(unknown.action, OutcomeAction.INCONCLUSIVE)

        arguments = list(self._build_inputs())
        first_metric = arguments[4][0]
        wrong_settings = tuple(replace(value, value=9.0) if value.name == "ps_min" else value for value in first_metric.settings)
        arguments[4] = (replace(first_metric, settings=wrong_settings), *arguments[4][1:])
        wrong_context = evaluate_outcome_classification(*arguments)
        self.assertIn("metric_setting_context_mismatch", wrong_context.reason_codes)
        self.assertEqual(wrong_context.action, OutcomeAction.INCONCLUSIVE)

        arguments = list(self._build_inputs())
        arguments[6] = arguments[6][1:]
        missing_journal_event = evaluate_outcome_classification(*arguments)
        self.assertIn("journal_entry_event_missing", missing_journal_event.reason_codes)
        self.assertEqual(missing_journal_event.action, OutcomeAction.INCONCLUSIVE)

    def test_effective_revised_proposal_is_supported(self) -> None:
        arguments = list(self._build_inputs())
        original = arguments[0]
        arguments[0] = replace(original, event_type=ExperimentEventType.EXPERIMENT_REVISED, payload=ExperimentRevisedPayload("event:earlier-proposal", original.payload.proposal))
        result = evaluate_outcome_classification(*arguments)
        self.assertEqual((result.classification, result.action), (OutcomeClassification.NO_MEANINGFUL_CHANGE, OutcomeAction.REVERT))

    def test_excluded_nights_are_disclosed_but_never_supply_values(self) -> None:
        arguments = list(self._build_inputs(pressure_baseline=[3.0] * 2))
        allocation = arguments[3]
        interval = AllocationInterval("session:night:excluded", -400_000, -100_000, ("quality:excluded",), ("excluded_for_test",))
        excluded = NightAllocation(
            record_id="allocation:night:excluded",
            night_record_id="night:excluded",
            local_date="2025-12-31",
            period=ExperimentPeriod.BASELINE,
            status=NightAllocationStatus.EXCLUDED,
            requested_intervals=(interval,),
            eligible_intervals=(),
            excluded_intervals=(interval,),
            exclusion_reason_codes=("excluded_for_test",),
            structural_quality_report_id="quality:structural:excluded",
            signal_quality_report_ids=(),
            quality_finding_ids=("quality:excluded",),
            caution_finding_ids=(),
        )
        arguments[3] = replace(allocation, nights=(excluded, *allocation.nights))
        arguments[4] = (
            *arguments[4],
            self._metric("night:excluded", ExperimentPeriod.BASELINE, MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP, 3.0),
            self._metric("night:excluded", ExperimentPeriod.BASELINE, MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, 1.2),
        )
        template = arguments[5][0]
        excluded_journal = replace(template, record_id="journal:night:excluded", night_record_id="night:excluded")
        arguments[5] = (*arguments[5], excluded_journal)
        arguments[6] = (
            *arguments[6],
            replace(
                self._event("event:journal:night:excluded", 100, ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED, SleepJournalEntryRecordedPayload(excluded_journal.record_id, excluded_journal.night_record_id)),
                source_record_ids=("experiment:one", excluded_journal.night_record_id),
            ),
        )
        result = evaluate_outcome_classification(*arguments)
        self.assertEqual(result.baseline_included_night_count, 2)
        self.assertEqual(result.outcome(OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP).baseline.count, 2)
        self.assertEqual(result.excluded_night_record_ids, ("night:excluded",))
        self.assertEqual((result.classification, result.action), (OutcomeClassification.INCONCLUSIVE, OutcomeAction.EXTEND))

    def test_result_retains_summaries_variability_versions_and_all_evidence(self) -> None:
        arguments = list(self._build_inputs(pressure_intervention=[2.5, 2.5, 3.0]))
        first = evaluate_outcome_classification(*arguments)
        arguments[4] = tuple(reversed(arguments[4]))
        arguments[5] = tuple(reversed(arguments[5]))
        arguments[6] = tuple(reversed(arguments[6]))
        second = evaluate_outcome_classification(*arguments)
        pressure = first.outcome(OutcomeId.MEAN_MASK_PRESSURE_ABOVE_EPAP)

        self.assertEqual(first, second)
        self.assertEqual((first.rule_set_id, first.rule_set_version), (OUTCOME_CLASSIFICATION_RULE_SET_ID, OUTCOME_CLASSIFICATION_RULE_SET_VERSION))
        self.assertEqual((pressure.baseline.minimum, pressure.baseline.median, pressure.baseline.maximum, pressure.baseline.median_absolute_deviation), (3.0, 3.0, 3.0, 0.0))
        self.assertEqual(tuple(value.value for value in pressure.intervention.values), (2.5, 2.5, 3.0))
        self.assertTrue(first.metric_result_ids and first.journal_entry_ids and first.experiment_event_ids)
        self.assertTrue(first.quality_report_ids and first.quality_finding_ids and first.source_record_ids and first.source_provenance_ids)
        self.assertTrue(any("does not establish causality" in value for value in first.limitations))
        with self.assertRaises(FrozenInstanceError):
            first.action = OutcomeAction.REVERT  # type: ignore[misc]

    def test_free_text_is_not_promoted_and_invalid_api_inputs_fail(self) -> None:
        result = self._evaluate(original_note="Terrible adverse effect and many awakenings")
        self.assertEqual((result.classification, result.action), (OutcomeClassification.NO_MEANINGFUL_CHANGE, OutcomeAction.REVERT))
        arguments = list(self._build_inputs())
        with self.assertRaisesRegex(OutcomeClassificationError, "immutable tuple"):
            evaluate_outcome_classification(*arguments[:4], list(arguments[4]), *arguments[5:])  # type: ignore[arg-type]

    def _evaluate(self, **changes):
        return evaluate_outcome_classification(*self._build_inputs(**changes))

    def _build_inputs(
        self,
        *,
        pressure_baseline=None,
        pressure_intervention=None,
        ventilation_baseline=None,
        ventilation_intervention=None,
        baseline_journal=None,
        intervention_journal=None,
        baseline_confounder_statuses=None,
        intervention_confounder_statuses=None,
        intervention_count=None,
        minimum_valid_nights=3,
        adverse_effect=False,
        original_note=None,
    ):
        pressure_baseline = [3.0] * 3 if pressure_baseline is None else pressure_baseline
        pressure_intervention = [3.0] * (intervention_count or 3) if pressure_intervention is None else pressure_intervention
        baseline_count = len(pressure_baseline)
        intervention_count = intervention_count or len(pressure_intervention)
        ventilation_baseline = [1.2] * baseline_count if ventilation_baseline is None else ventilation_baseline
        ventilation_intervention = [1.2] * intervention_count if ventilation_intervention is None else ventilation_intervention
        baseline_nights = tuple(f"night:b:{index}" for index in range(baseline_count))
        intervention_nights = tuple(f"night:i:{index}" for index in range(intervention_count))
        all_nights = (*baseline_nights, *intervention_nights)
        applied_at_ms = 3_000_000
        change = ExperimentSettingChange(ExperimentSetting("ps_min", 2.0, "cm H₂O"), ExperimentSetting("ps_min", 1.0, "cm H₂O"))
        baseline_settings = (
            ExperimentSetting("therapy_mode_code", 6),
            ExperimentSetting("loader_mode_code", 7),
            ExperimentSetting("epap", 10.0, "cm H₂O"),
            change.previous,
            ExperimentSetting("ps_max", 5.0, "cm H₂O"),
            ExperimentSetting("max_ipap", 15.0, "cm H₂O"),
        )
        proposal = ExperimentProposal(
            problem_event_id="event:problem",
            hypothesis_event_id="event:hypothesis",
            baseline_local_dates=tuple(f"2026-01-{index + 1:02d}" for index in range(max(1, baseline_count))),
            baseline_settings=baseline_settings,
            proposed_change=change,
            settings_held_fixed=tuple(value for value in baseline_settings if value.name != "ps_min"),
            evidence_record_ids=("night:evidence", "session:evidence", "signal:evidence"),
            representative_intervals=(ExperimentEvidenceInterval("night:evidence", "session:evidence", 0, 1, ("night:evidence", "session:evidence", "signal:evidence")),),
            expected_objective_effects=("Lower pressure exposure",),
            expected_subjective_effects=("Better sleep",),
            minimum_valid_nights=minimum_valid_nights,
            invalid_night_criteria=("Insufficient quality",),
            possible_adverse_effects=("Worsening",),
            stop_conditions=("Stop if worse",),
            revert_conditions=("Revert if worse",),
        )
        proposal_event = self._event("event:proposal", 1, ExperimentEventType.EXPERIMENT_PROPOSED, ExperimentProposedPayload(proposal))
        acceptance_event = self._event("event:accepted", 2, ExperimentEventType.EXPERIMENT_ACCEPTED, ExperimentDecisionPayload(proposal_event.record_id, "Accepted for test"))
        setting_event = self._event("event:change", 3, ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED, SettingChangeConfirmedPayload(acceptance_event.record_id, change, applied_at_ms))
        allocation_nights = []
        for index, night_id in enumerate(all_nights):
            period = ExperimentPeriod.BASELINE if night_id in baseline_nights else ExperimentPeriod.INTERVENTION
            session_id = f"session:{night_id}"
            interval = AllocationInterval(session_id, index * 400_000, index * 400_000 + 300_000)
            allocation_nights.append(
                NightAllocation(
                    record_id=f"allocation:{night_id}",
                    night_record_id=night_id,
                    local_date=f"2026-01-{index + 1:02d}",
                    period=period,
                    status=NightAllocationStatus.INCLUDED,
                    requested_intervals=(interval,),
                    eligible_intervals=(interval,),
                    excluded_intervals=(),
                    exclusion_reason_codes=(),
                    structural_quality_report_id=f"quality:structural:{night_id}",
                    signal_quality_report_ids=(f"quality:signal:{night_id}",),
                    quality_finding_ids=(f"quality:finding:{night_id}",),
                    caution_finding_ids=(),
                )
            )
        allocation = ExperimentNightAllocation("allocation:experiment", setting_event.record_id, applied_at_ms, tuple(allocation_nights))
        metrics = []
        for period, night_ids, pressure_values, ventilation_values in (
            (ExperimentPeriod.BASELINE, baseline_nights, pressure_baseline, ventilation_baseline),
            (ExperimentPeriod.INTERVENTION, intervention_nights, pressure_intervention, ventilation_intervention),
        ):
            for index, value in enumerate(pressure_values):
                metrics.append(self._metric(night_ids[index], period, MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP, value))
            for index, value in enumerate(ventilation_values):
                metrics.append(self._metric(night_ids[index], period, MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO, value))
        journals = []
        default_baseline = {"awakenings_count": [2] * baseline_count, "sleep_quality": [3] * baseline_count, "morning_energy": [3] * baseline_count, "daytime_tiredness": [3] * baseline_count}
        default_intervention = {"awakenings_count": [2] * intervention_count, "sleep_quality": [3] * intervention_count, "morning_energy": [3] * intervention_count, "daytime_tiredness": [3] * intervention_count}
        default_baseline.update(baseline_journal or {})
        default_intervention.update(intervention_journal or {})
        baseline_confounder_statuses = baseline_confounder_statuses or [ConfounderReportStatus.NONE_REPORTED] * baseline_count
        intervention_confounder_statuses = intervention_confounder_statuses or [ConfounderReportStatus.NONE_REPORTED] * intervention_count
        for period, night_ids, fields, statuses in (
            (ExperimentPeriod.BASELINE, baseline_nights, default_baseline, baseline_confounder_statuses),
            (ExperimentPeriod.INTERVENTION, intervention_nights, default_intervention, intervention_confounder_statuses),
        ):
            for index, night_id in enumerate(night_ids):
                status = statuses[index]
                confounders = (SleepJournalConfounder(ConfounderKind.STRESS, "Synthetic stress"),) if status is ConfounderReportStatus.REPORTED else ()
                journals.append(
                    SleepJournalEntry(
                        record_id=f"journal:{night_id}",
                        night_record_id=night_id,
                        reported_at_ms=10_000 + len(journals),
                        reported_by="user:local",
                        awakenings_count=fields["awakenings_count"][index],
                        sleep_quality=fields["sleep_quality"][index],
                        morning_energy=fields["morning_energy"][index],
                        daytime_tiredness=fields["daytime_tiredness"][index],
                        confounder_status=status,
                        confounders=confounders,
                        original_note=original_note,
                        source_provenance_ids=(f"provenance:journal:{night_id}",),
                    )
                )
        evidence_events = tuple(
            replace(
                self._event(f"event:{entry.record_id}", 10 + index, ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED, SleepJournalEntryRecordedPayload(entry.record_id, entry.night_record_id)),
                source_record_ids=("experiment:one", entry.night_record_id),
            )
            for index, entry in enumerate(journals)
        )
        if adverse_effect:
            evidence_events = (*evidence_events, self._event("event:adverse", 100, ExperimentEventType.ADVERSE_EFFECT_RECORDED, ObservationRecordedPayload("Synthetic adverse effect", 20_000, intervention_nights[0] if intervention_nights else None)))
        return proposal_event, acceptance_event, setting_event, allocation, tuple(metrics), tuple(journals), evidence_events

    @staticmethod
    def _event(record_id, sequence, event_type, payload):
        return ExperimentEvent(
            record_id=record_id,
            experiment_record_id="experiment:one",
            sequence_number=sequence,
            event_type=event_type,
            recorded_at_ms=1_000 + sequence,
            recorded_by="user:local",
            payload=payload,
            source_class=SourceClass.USER_REPORTED,
            source_record_ids=("experiment:one",),
            source_provenance_ids=("provenance:user",),
        )

    @staticmethod
    def _metric(night_id, period, metric_id, value):
        session_id = f"session:{night_id}"
        ps_min = 2.0 if period is ExperimentPeriod.BASELINE else 1.0
        settings = tuple(
            MetricSettingValue(session_id, f"setting:{night_id}:{name}", name, setting_value, unit)
            for name, setting_value, unit in (
                ("therapy_mode_code", 6, None),
                ("loader_mode_code", 7, None),
                ("epap", 10.0, "cm H₂O"),
                ("ps_min", ps_min, "cm H₂O"),
                ("ps_max", 5.0, "cm H₂O"),
                ("max_ipap", 15.0, "cm H₂O"),
            )
        )
        measurements = ()
        observation_count = 0
        algorithm_version = MEAN_MASK_PRESSURE_ABOVE_EPAP_ALGORITHM_VERSION
        unit = "cm H₂O"
        if metric_id is MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO:
            algorithm_version = MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION
            unit = "1"
            measurements = (MetricValue("ventilation_q50_l_min", 10.0, "L/min"), MetricValue("ventilation_q95_l_min", float(value) * 10.0, "L/min"))
            observation_count = 20
        interval = MetricInterval(session_id, 0, 300_000, source_segment_ids=(f"segment:{night_id}",))
        return MetricResult(
            record_id=f"metric:{metric_id.value}:{night_id}",
            metric_id=metric_id,
            algorithm_version=algorithm_version,
            status=MetricStatus.CALCULATED,
            reason_code=MetricReason.CALCULATED,
            value=float(value),
            unit=unit,
            parameters=(),
            settings=settings,
            night_record_id=night_id,
            session_record_ids=(session_id,),
            setting_record_ids=tuple(value.setting_record_id for value in settings),
            source_record_ids=(night_id, session_id),
            source_provenance_ids=(f"provenance:metric:{night_id}",),
            quality_report_ids=(f"quality:metric-report:{night_id}:{metric_id.value}",),
            quality_finding_ids=(f"quality:metric-finding:{night_id}:{metric_id.value}",),
            requested_intervals=(interval,),
            eligible_intervals=(interval,),
            excluded_intervals=(),
            requested_duration_ms=300_000,
            eligible_duration_ms=300_000,
            excluded_duration_ms=0,
            sample_cell_count=1,
            limitations=("Synthetic classification evidence.",),
            measurements=measurements,
            observation_count=observation_count,
        )


if __name__ == "__main__":
    unittest.main()
