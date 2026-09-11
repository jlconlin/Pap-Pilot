"""Focused tests for generic analysis composition and read-only API resources."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from pap_pilot.api import (
    ANALYSIS_EVIDENCE_DETAIL_PATH,
    ANALYSIS_EXPERIMENT_DETAIL_PATH,
    ANALYSIS_NIGHT_DETAIL_PATH,
    ANALYSIS_NIGHTS_PATH,
    ANALYSIS_OVERVIEW_PATH,
    ANALYSIS_RESOURCE_FORMAT,
    ANALYSIS_RESOURCE_FORMAT_VERSION,
    ANALYSIS_TREND_DETAIL_PATH,
    ANALYSIS_TRENDS_PATH,
    PS_MIN_EXPERIMENT_SUMMARY_PATH,
    create_app,
)
from pap_pilot.engine import (
    ANALYSIS_WORKSPACE_FORMAT,
    AnalysisAvailability,
    AnalysisEvidenceKind,
    AnalysisExperimentReference,
    AnalysisResourceKind,
    ExperimentStore,
    build_ps_min_retrospective_evidence_report,
    analysis_resource_id,
    reconstruct_ps_min_experiment_fixture,
    record_retrospective_protocol,
    record_retrospective_user_evidence,
    serialize_retrospective_evidence_report,
)
from pap_pilot.workflow import compose_analysis_workspace, evaluate_selected_oscar_retrospective_experiment
from tests.test_retrospective_evaluation import _cohort, _generic_cohort, _journal_inputs, _proposal, _protocol


class AnalysisApiTests(unittest.TestCase):
    """Prove generic routes preserve records, missing states, and legacy behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = TemporaryDirectory()
        database_path = Path(cls.temporary_directory.name) / "pap_pilot.sqlite3"
        oscar_cohort = _cohort()
        cohort = _generic_cohort(oscar_cohort)
        fixture = reconstruct_ps_min_experiment_fixture()
        proposal = _proposal(fixture, cohort)
        with ExperimentStore(database_path) as store:
            store.create_experiment(fixture.experiment)
            store.append_events(fixture.history)
            record_retrospective_protocol(store, fixture.experiment.record_id, cohort, _protocol(fixture, proposal))
            replayed = record_retrospective_user_evidence(store, fixture.experiment.record_id, cohort, _journal_inputs(cohort))
        evaluation = evaluate_selected_oscar_retrospective_experiment(oscar_cohort, replayed)
        cls.evaluation = evaluation
        experiment = AnalysisExperimentReference(
            experiment_record_id="experiment:generic-synthetic",
            label="Synthetic optional experiment",
            resource_id=analysis_resource_id(AnalysisResourceKind.EXPERIMENT, "experiment:generic-synthetic"),
            summary_record_id="report:generic-synthetic",
            availability=AnalysisAvailability.AVAILABLE,
            source_record_ids=("experiment:generic-synthetic", "report:generic-synthetic"),
            source_provenance_ids=(evaluation.source_provenance_ids[0],),
            limitations=("Synthetic API fixture only.",),
        )
        cls.workspace = compose_analysis_workspace(
            evaluation.selected_nights,
            structural_quality_reports=(*evaluation.allocation_structural_quality_reports, *evaluation.metric_structural_quality_reports),
            signal_quality_reports=evaluation.signal_quality_reports,
            metric_results=evaluation.metric_results,
            journal_entries=evaluation.effective_journal_entries,
            experiments=(experiment,),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_overview_and_recent_nights_are_generic_versioned_and_provenance_linked(self) -> None:
        with TestClient(create_app(analysis_workspace=self.workspace)) as client:
            overview_response = client.get(ANALYSIS_OVERVIEW_PATH)
            nights_response = client.get(ANALYSIS_NIGHTS_PATH)

        overview = overview_response.json()
        nights = nights_response.json()
        self.assertEqual(overview_response.status_code, 200)
        self.assertEqual(overview["format"], ANALYSIS_WORKSPACE_FORMAT)
        self.assertEqual(overview["workspace"]["record_id"], self.workspace.record_id)
        self.assertEqual(overview["workspace"]["experiments"][0]["experiment_record_id"], "experiment:generic-synthetic")
        self.assertTrue(overview["workspace"]["source_record_ids"])
        self.assertTrue(overview["workspace"]["source_provenance_ids"])
        self.assertEqual(nights_response.status_code, 200)
        self.assertEqual((nights["format"], nights["format_version"]), (ANALYSIS_RESOURCE_FORMAT, ANALYSIS_RESOURCE_FORMAT_VERSION))
        self.assertEqual(nights["resource"]["kind"], "night_collection")
        self.assertEqual(len(nights["nights"]), 6)
        self.assertEqual(
            [value["local_date"] for value in nights["nights"]],
            sorted((value.local_date for value in self.workspace.nights), reverse=True),
        )
        self.assertEqual(nights_response.headers["cache-control"], "no-store")
        self.assertEqual(nights_response.headers["x-content-type-options"], "nosniff")

    def test_available_generic_analysis_does_not_require_an_experiment(self) -> None:
        night = self.evaluation.selected_nights[0]
        session_ids = {value.record_id for value in night.sessions}
        workspace = compose_analysis_workspace(
            (night,),
            structural_quality_reports=tuple(value for value in (*self.evaluation.allocation_structural_quality_reports, *self.evaluation.metric_structural_quality_reports) if value.night_record_id == night.record_id),
            signal_quality_reports=tuple(value for value in self.evaluation.signal_quality_reports if value.session_record_id in session_ids),
            metric_results=tuple(value for value in self.evaluation.metric_results if value.night_record_id == night.record_id),
            journal_entries=tuple(value for value in self.evaluation.effective_journal_entries if value.night_record_id == night.record_id),
        )
        missing_event_evidence = next(value for value in workspace.evidence if value.kind is AnalysisEvidenceKind.EVENT)
        with TestClient(create_app(analysis_workspace=workspace)) as client:
            response = client.get(ANALYSIS_OVERVIEW_PATH)
            missing_response = client.get(ANALYSIS_EVIDENCE_DETAIL_PATH.format(evidence_record_id=missing_event_evidence.record_id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"]["experiments"], [])
        self.assertEqual(len(response.json()["workspace"]["nights"]), 1)
        self.assertEqual(len(response.json()["workspace"]["trends"]), 2)
        self.assertEqual(missing_response.json()["resource"]["availability"], "unavailable")
        self.assertEqual(missing_response.json()["evidence"]["reason_codes"], ["no_normalized_event_records"])

    def test_composition_is_deterministic_for_the_same_existing_records(self) -> None:
        repeated = compose_analysis_workspace(
            tuple(reversed(self.evaluation.selected_nights)),
            structural_quality_reports=tuple(reversed((*self.evaluation.allocation_structural_quality_reports, *self.evaluation.metric_structural_quality_reports))),
            signal_quality_reports=tuple(reversed(self.evaluation.signal_quality_reports)),
            metric_results=tuple(reversed(self.evaluation.metric_results)),
            journal_entries=tuple(reversed(self.evaluation.effective_journal_entries)),
            experiments=self.workspace.experiments,
        )

        self.assertEqual(repeated, self.workspace)

    def test_night_trend_quality_and_optional_experiment_resources_resolve(self) -> None:
        night = self.workspace.nights[0]
        trend = self.workspace.trends[0]
        quality = next(value for value in self.workspace.evidence if value.kind is AnalysisEvidenceKind.QUALITY)
        experiment = self.workspace.experiments[0]
        with TestClient(create_app(analysis_workspace=self.workspace)) as client:
            night_response = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=night.night_record_id))
            trend_response = client.get(ANALYSIS_TREND_DETAIL_PATH.format(trend_record_id=trend.record_id))
            evidence_response = client.get(ANALYSIS_EVIDENCE_DETAIL_PATH.format(evidence_record_id=quality.record_id))
            experiment_response = client.get(ANALYSIS_EXPERIMENT_DETAIL_PATH.format(experiment_record_id=experiment.experiment_record_id))

        night_payload = night_response.json()
        self.assertEqual(night_payload["night"]["night_record_id"], night.night_record_id)
        self.assertTrue(night_payload["night"]["quality_report_ids"])
        self.assertEqual(len(night_payload["night"]["metric_result_ids"]), 2)
        self.assertEqual(len(night_payload["night"]["journal_entry_ids"]), 1)
        self.assertTrue(night_payload["night"]["source_provenance_ids"])
        trend_payload = trend_response.json()
        self.assertEqual(trend_payload["trend"]["metric_id"], trend.metric_id)
        self.assertEqual(len(trend_payload["trend"]["points"]), 6)
        self.assertTrue(all(value["availability"] == "available" for value in trend_payload["trend"]["points"]))
        evidence_payload = evidence_response.json()
        self.assertEqual(evidence_payload["evidence"]["kind"], "quality")
        self.assertTrue(any(value.startswith(("quality-report:", "signal-quality-report:")) for value in evidence_payload["evidence"]["source_record_ids"]))
        self.assertTrue(evidence_payload["evidence"]["source_provenance_ids"])
        self.assertTrue(all(value.count(":") >= 2 for value in evidence_payload["evidence"]["reason_codes"]))
        self.assertEqual(experiment_response.json()["experiment"]["compatibility_fixture_id"], None)

    def test_unconfigured_collections_and_unknown_details_are_explicit(self) -> None:
        with TestClient(create_app()) as client:
            overview = client.get(ANALYSIS_OVERVIEW_PATH)
            nights = client.get(ANALYSIS_NIGHTS_PATH)
            trends = client.get(ANALYSIS_TRENDS_PATH)
            missing_night = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id="night:unknown"))
            missing_evidence = client.get(ANALYSIS_EVIDENCE_DETAIL_PATH.format(evidence_record_id="evidence:unknown"))

        self.assertEqual(overview.json()["workspace"]["availability"], "unavailable")
        self.assertEqual(overview.json()["workspace"]["reason_codes"], ["analysis_workspace_not_configured"])
        self.assertEqual(nights.json()["resource"]["availability"], "unavailable")
        self.assertEqual(nights.json()["nights"], [])
        self.assertEqual(trends.json()["resource"]["availability"], "unavailable")
        self.assertEqual(trends.json()["trends"], [])
        self.assertEqual(missing_night.status_code, 404)
        self.assertEqual(missing_evidence.status_code, 404)
        self.assertEqual(missing_night.headers["cache-control"], "no-store")

    def test_generic_responses_are_frozen_at_app_creation(self) -> None:
        application = create_app(analysis_workspace=self.workspace)
        with patch("pap_pilot.api.server.serialize_analysis_workspace", side_effect=AssertionError("request-time rebuild")):
            with TestClient(application) as client:
                self.assertEqual(client.get(ANALYSIS_OVERVIEW_PATH).status_code, 200)
                self.assertEqual(client.get(ANALYSIS_NIGHTS_PATH).status_code, 200)

    def test_generic_resources_are_get_only(self) -> None:
        paths = (
            ANALYSIS_OVERVIEW_PATH,
            ANALYSIS_NIGHTS_PATH,
            ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=self.workspace.nights[0].night_record_id),
            ANALYSIS_TRENDS_PATH,
            ANALYSIS_TREND_DETAIL_PATH.format(trend_record_id=self.workspace.trends[0].record_id),
            ANALYSIS_EVIDENCE_DETAIL_PATH.format(evidence_record_id=self.workspace.evidence[0].record_id),
            ANALYSIS_EXPERIMENT_DETAIL_PATH.format(experiment_record_id=self.workspace.experiments[0].experiment_record_id),
        )
        with TestClient(create_app(analysis_workspace=self.workspace)) as client:
            for path in paths:
                for method in ("POST", "PUT", "PATCH", "DELETE"):
                    with self.subTest(path=path, method=method):
                        self.assertEqual(client.request(method, path, json={"ignored": True}).status_code, 405)

    def test_ps_min_summary_remains_byte_for_byte_compatible(self) -> None:
        expected = serialize_retrospective_evidence_report(build_ps_min_retrospective_evidence_report()).encode("utf-8")
        with TestClient(create_app(analysis_workspace=self.workspace)) as client:
            response = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, expected)


if __name__ == "__main__":
    unittest.main()
