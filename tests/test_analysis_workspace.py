"""Focused tests for the generic source-independent analysis workspace."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from pap_pilot.engine import (
    ANALYSIS_WORKSPACE_FORMAT,
    ANALYSIS_WORKSPACE_FORMAT_VERSION,
    ANALYSIS_WORKSPACE_SCHEMA_ID,
    ANALYSIS_WORKSPACE_SCHEMA_VERSION,
    AnalysisAvailability,
    AnalysisEvidence,
    AnalysisEvidenceKind,
    AnalysisExperimentReference,
    AnalysisModelError,
    AnalysisNight,
    AnalysisResource,
    AnalysisResourceKind,
    AnalysisTrend,
    AnalysisTrendPoint,
    AnalysisWorkspace,
    analysis_resource_id,
    serialize_analysis_workspace,
)


class AnalysisWorkspaceTests(unittest.TestCase):
    """Verify generic identity, evidence, missing-state, and compatibility contracts."""

    def _evidence(self) -> AnalysisEvidence:
        return AnalysisEvidence(
            record_id="evidence:signal:night-1",
            kind=AnalysisEvidenceKind.SIGNAL,
            label="Flow Rate",
            availability=AnalysisAvailability.AVAILABLE,
            night_record_ids=("night:1",),
            session_record_ids=("session:1",),
            source_record_ids=("signal:flow:1",),
            source_provenance_ids=("provenance:flow:1",),
            limitations=("Waveform evidence does not establish sleep state.",),
        )

    def _night(self) -> AnalysisNight:
        return AnalysisNight(
            record_id="analysis-night:1",
            night_record_id="night:1",
            local_date="2026-09-01",
            availability=AnalysisAvailability.AVAILABLE,
            session_record_ids=("session:1",),
            setting_record_ids=("setting:epap:1",),
            event_record_ids=("event:oa:1",),
            signal_record_ids=("signal:flow:1",),
            quality_report_ids=("quality:night:1",),
            metric_result_ids=(),
            journal_entry_ids=(),
            evidence_record_ids=("evidence:signal:night-1",),
            source_record_ids=("night:1", "session:1", "setting:epap:1", "event:oa:1", "signal:flow:1", "quality:night:1"),
            source_provenance_ids=("provenance:flow:1", "provenance:night:1"),
            limitations=("No experiment is required to inspect this night.",),
        )

    def _trend(self) -> AnalysisTrend:
        point = AnalysisTrendPoint(
            night_record_id="night:1",
            local_date="2026-09-01",
            value=0.4,
            availability=AnalysisAvailability.AVAILABLE,
            source_record_ids=("metric:example:night-1",),
            source_provenance_ids=("provenance:metric:1",),
        )
        return AnalysisTrend(
            record_id="trend:example",
            metric_id="example_metric",
            label="Example metric",
            unit="1",
            availability=AnalysisAvailability.AVAILABLE,
            points=(point,),
            source_record_ids=("metric:example:night-1",),
            source_provenance_ids=("provenance:metric:1",),
            limitations=("Synthetic contract value only.",),
        )

    def _resources(self, *, experiment_id: str | None = None) -> tuple[AnalysisResource, ...]:
        values = [
            AnalysisResource(
                analysis_resource_id(AnalysisResourceKind.OVERVIEW, "workspace:personal"),
                AnalysisResourceKind.OVERVIEW,
                "workspace:personal",
                AnalysisAvailability.AVAILABLE,
            ),
            AnalysisResource(
                analysis_resource_id(AnalysisResourceKind.NIGHT_COLLECTION, "workspace:personal"),
                AnalysisResourceKind.NIGHT_COLLECTION,
                "workspace:personal",
                AnalysisAvailability.AVAILABLE,
            ),
            AnalysisResource(
                analysis_resource_id(AnalysisResourceKind.NIGHT_DETAIL, "night:1"),
                AnalysisResourceKind.NIGHT_DETAIL,
                "night:1",
                AnalysisAvailability.AVAILABLE,
            ),
            AnalysisResource(
                analysis_resource_id(AnalysisResourceKind.TREND_COLLECTION, "workspace:personal"),
                AnalysisResourceKind.TREND_COLLECTION,
                "workspace:personal",
                AnalysisAvailability.AVAILABLE,
            ),
            AnalysisResource(
                analysis_resource_id(AnalysisResourceKind.TREND_DETAIL, "trend:example"),
                AnalysisResourceKind.TREND_DETAIL,
                "trend:example",
                AnalysisAvailability.AVAILABLE,
            ),
            AnalysisResource(
                analysis_resource_id(AnalysisResourceKind.EVIDENCE, "evidence:signal:night-1"),
                AnalysisResourceKind.EVIDENCE,
                "evidence:signal:night-1",
                AnalysisAvailability.AVAILABLE,
            ),
        ]
        if experiment_id is not None:
            values.append(
                AnalysisResource(
                    analysis_resource_id(AnalysisResourceKind.EXPERIMENT, experiment_id),
                    AnalysisResourceKind.EXPERIMENT,
                    experiment_id,
                    AnalysisAvailability.AVAILABLE,
                )
            )
        return tuple(reversed(values))

    def _workspace(self, *, include_experiment: bool = False) -> AnalysisWorkspace:
        experiments: tuple[AnalysisExperimentReference, ...] = ()
        source_records = (
            "event:oa:1",
            "metric:example:night-1",
            "night:1",
            "quality:night:1",
            "session:1",
            "setting:epap:1",
            "signal:flow:1",
        )
        source_provenance = ("provenance:flow:1", "provenance:metric:1", "provenance:night:1")
        experiment_id = None
        if include_experiment:
            experiment_id = "experiment:ps-min-2-to-1"
            experiments = (
                AnalysisExperimentReference(
                    experiment_record_id=experiment_id,
                    label="PS Min 2 to 1 retrospective example",
                    resource_id=analysis_resource_id(AnalysisResourceKind.EXPERIMENT, experiment_id),
                    summary_record_id="report:ps-min-2-to-1",
                    availability=AnalysisAvailability.AVAILABLE,
                    source_record_ids=(experiment_id, "report:ps-min-2-to-1"),
                    source_provenance_ids=("provenance:ps-min-fixture",),
                    compatibility_fixture_id="pap-pilot.ps-min-retrospective",
                    limitations=("Compatibility fixture; not the workspace identity.",),
                ),
            )
            source_records += (experiment_id, "report:ps-min-2-to-1")
            source_provenance += ("provenance:ps-min-fixture",)
        return AnalysisWorkspace(
            record_id="workspace:personal",
            title="PAP analysis",
            availability=AnalysisAvailability.AVAILABLE,
            nights=(self._night(),),
            trends=(self._trend(),),
            evidence=(self._evidence(),),
            resources=self._resources(experiment_id=experiment_id),
            experiments=experiments,
            source_record_ids=source_records,
            source_provenance_ids=source_provenance,
            limitations=("Analysis is advisory and does not change device settings.",),
        )

    def test_workspace_is_generic_and_does_not_require_an_experiment(self) -> None:
        workspace = self._workspace()

        self.assertEqual(workspace.experiments, ())
        self.assertEqual(workspace.nights[0].night_record_id, "night:1")
        self.assertEqual(workspace.trends[0].metric_id, "example_metric")
        self.assertEqual(workspace.schema_id, ANALYSIS_WORKSPACE_SCHEMA_ID)
        self.assertEqual(workspace.schema_version, ANALYSIS_WORKSPACE_SCHEMA_VERSION)

    def test_resource_identifiers_are_stable_and_not_ps_min_specific(self) -> None:
        self.assertEqual(analysis_resource_id(AnalysisResourceKind.OVERVIEW, "workspace:any"), "analysis:overview")
        self.assertEqual(analysis_resource_id(AnalysisResourceKind.NIGHT_COLLECTION, "workspace:any"), "analysis:nights")
        self.assertEqual(analysis_resource_id(AnalysisResourceKind.NIGHT_DETAIL, "night:42"), "analysis:night:night:42")
        self.assertEqual(analysis_resource_id(AnalysisResourceKind.TREND_COLLECTION, "workspace:any"), "analysis:trends")
        self.assertEqual(analysis_resource_id(AnalysisResourceKind.TREND_DETAIL, "trend:leak"), "analysis:trend:trend:leak")

        with self.assertRaisesRegex(AnalysisModelError, "does not match"):
            AnalysisResource("analysis:ps-min", AnalysisResourceKind.NIGHT_DETAIL, "night:42", AnalysisAvailability.AVAILABLE)

    def test_ps_min_is_an_optional_compatibility_reference(self) -> None:
        workspace = self._workspace(include_experiment=True)

        self.assertEqual(len(workspace.experiments), 1)
        reference = workspace.experiments[0]
        self.assertEqual(reference.compatibility_fixture_id, "pap-pilot.ps-min-retrospective")
        self.assertEqual(reference.experiment_record_id, "experiment:ps-min-2-to-1")
        self.assertNotEqual(reference.resource_id, "analysis:overview")

    def test_missing_and_partial_evidence_remain_explicit(self) -> None:
        missing_point = AnalysisTrendPoint(
            night_record_id="night:2",
            local_date="2026-09-02",
            value=None,
            availability=AnalysisAvailability.UNAVAILABLE,
            source_record_ids=(),
            source_provenance_ids=(),
            reason_codes=("metric_not_calculated",),
        )
        available_point = self._trend().points[0]
        trend = AnalysisTrend(
            record_id="trend:partial",
            metric_id="generic_metric",
            label="Generic metric",
            unit=None,
            availability=AnalysisAvailability.PARTIAL,
            points=(missing_point, available_point),
            source_record_ids=("metric:example:night-1",),
            source_provenance_ids=("provenance:metric:1",),
            reason_codes=("one_or_more_points_unavailable",),
            limitations=("Missing values are not imputed.",),
        )

        self.assertIsNone(trend.points[1].value)
        self.assertEqual(trend.points[1].reason_codes, ("metric_not_calculated",))
        with self.assertRaisesRegex(AnalysisModelError, "non-available trend point"):
            AnalysisTrendPoint("night:2", "2026-09-02", 0, AnalysisAvailability.UNAVAILABLE, (), (), ("missing",))

        empty_trend = AnalysisTrend(
            record_id="trend:empty",
            metric_id="generic_metric",
            label="Generic metric",
            unit=None,
            availability=AnalysisAvailability.UNAVAILABLE,
            points=(),
            source_record_ids=(),
            source_provenance_ids=(),
            reason_codes=("no_therapy_nights",),
        )
        self.assertEqual(empty_trend.points, ())

        with self.assertRaisesRegex(AnalysisModelError, "cannot be partially available"):
            AnalysisTrendPoint("night:2", "2026-09-02", None, AnalysisAvailability.PARTIAL, (), (), ("partial",))

    def test_workspace_requires_resolvable_resources_and_evidence(self) -> None:
        workspace = self._workspace()
        bad_night = AnalysisNight(
            record_id="analysis-night:bad",
            night_record_id="night:bad",
            local_date="2026-09-03",
            availability=AnalysisAvailability.AVAILABLE,
            session_record_ids=("session:bad",),
            setting_record_ids=(),
            event_record_ids=(),
            signal_record_ids=(),
            quality_report_ids=(),
            metric_result_ids=(),
            journal_entry_ids=(),
            evidence_record_ids=("evidence:missing",),
            source_record_ids=("night:bad", "session:bad"),
            source_provenance_ids=("provenance:bad",),
        )
        with self.assertRaisesRegex(AnalysisModelError, "evidence identifier"):
            AnalysisWorkspace(
                record_id=workspace.record_id,
                title=workspace.title,
                availability=workspace.availability,
                nights=(bad_night,),
                trends=(),
                evidence=(),
                resources=(
                    AnalysisResource(
                        analysis_resource_id(AnalysisResourceKind.OVERVIEW, workspace.record_id),
                        AnalysisResourceKind.OVERVIEW,
                        workspace.record_id,
                        AnalysisAvailability.AVAILABLE,
                    ),
                ),
                experiments=(),
                source_record_ids=("night:bad", "session:bad"),
                source_provenance_ids=("provenance:bad",),
            )

    def test_workspace_requires_complete_nested_provenance(self) -> None:
        workspace = self._workspace()
        with self.assertRaisesRegex(AnalysisModelError, "Workspace provenance"):
            AnalysisWorkspace(
                record_id=workspace.record_id,
                title=workspace.title,
                availability=workspace.availability,
                nights=workspace.nights,
                trends=workspace.trends,
                evidence=workspace.evidence,
                resources=workspace.resources,
                experiments=workspace.experiments,
                source_record_ids=("night:1",),
                source_provenance_ids=workspace.source_provenance_ids,
            )

    def test_serialization_is_versioned_deterministic_and_immutable(self) -> None:
        workspace = self._workspace(include_experiment=True)
        serialized = serialize_analysis_workspace(workspace)
        payload = json.loads(serialized)

        self.assertEqual(serialized, serialize_analysis_workspace(workspace))
        self.assertNotIn("\n", serialized)
        self.assertEqual(payload["format"], ANALYSIS_WORKSPACE_FORMAT)
        self.assertEqual(payload["format_version"], ANALYSIS_WORKSPACE_FORMAT_VERSION)
        self.assertEqual(payload["workspace"]["availability"], "available")
        self.assertEqual(payload["workspace"]["resources"][0]["resource_id"], "analysis:evidence:evidence:signal:night-1")
        self.assertTrue(serialize_analysis_workspace(workspace, indent=2).endswith("\n"))
        with self.assertRaises(FrozenInstanceError):
            workspace.title = "changed"  # type: ignore[misc]

    def test_contract_has_no_adapter_api_ui_or_ai_dependency(self) -> None:
        source = (Path(__file__).parents[1] / "src/pap_pilot/engine/analysis/model.py").read_text(encoding="utf-8")
        for forbidden in ("pap_pilot.adapter", "pap_pilot.api", "pap_pilot.ui", "pap_pilot.engine.ai", "sqlite3"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
