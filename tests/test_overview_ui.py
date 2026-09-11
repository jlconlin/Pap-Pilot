"""Focused browser-asset and rendering tests for the general analysis overview."""

from html import unescape
from importlib.resources import files
import json
import shutil
import subprocess
import unittest

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from pap_pilot.api import (
    ANALYSIS_NIGHTS_PATH,
    ANALYSIS_OVERVIEW_PATH,
    ANALYSIS_TRENDS_PATH,
    LOCAL_NIGHT_DETAIL_PATH,
    LOCAL_NIGHT_DETAIL_SCRIPT_PATH,
    LOCAL_OVERVIEW_PATH,
    LOCAL_OVERVIEW_SCRIPT_PATH,
    LOCAL_OVERVIEW_STYLES_PATH,
    create_app,
)
from pap_pilot.ui import OVERVIEW_ASSET_NAMES, load_overview_asset


class GeneralAnalysisOverviewTests(unittest.TestCase):
    """Verify that the landing page is generic, local, and honest about missing data."""

    def test_overview_shell_and_assets_are_served_locally(self) -> None:
        with TestClient(create_app()) as client:
            page = client.get(LOCAL_OVERVIEW_PATH)
            styles = client.get(LOCAL_OVERVIEW_STYLES_PATH)
            script = client.get(LOCAL_OVERVIEW_SCRIPT_PATH)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(styles.status_code, 200)
        self.assertEqual(script.status_code, 200)
        self.assertEqual(page.text, load_overview_asset("overview.html"))
        self.assertEqual(styles.text, load_overview_asset("overview.css"))
        self.assertEqual(script.text, load_overview_asset("overview.mjs"))
        self.assertTrue(page.headers["content-type"].startswith("text/html"))
        self.assertTrue(styles.headers["content-type"].startswith("text/css"))
        self.assertTrue(script.headers["content-type"].startswith("text/javascript"))
        for response in (page, styles, script):
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            self.assertIn("connect-src 'self'", response.headers["content-security-policy"])

    def test_shell_loads_only_local_assets_and_generic_analysis_feeds(self) -> None:
        shell = load_overview_asset("overview.html")
        script = load_overview_asset("overview.mjs")
        combined = f"{shell}\n{script}".lower()

        self.assertIn('id="overview"', shell)
        self.assertIn('href="/assets/overview.css"', shell)
        self.assertIn('src="/assets/overview.mjs"', shell)
        for endpoint in (ANALYSIS_OVERVIEW_PATH, ANALYSIS_NIGHTS_PATH, ANALYSIS_TRENDS_PATH):
            self.assertIn(endpoint, script)
        self.assertIn("Promise.all", script)
        self.assertIn("general pap analysis", combined)
        self.assertIn("missing values shown as gaps", script)
        self.assertNotIn("http://", combined)
        self.assertNotIn("https://", combined)
        self.assertNotIn("boundary-corrections", script)
        self.assertNotIn("<form", combined)
        self.assertNotIn("<canvas", combined)

    def test_ui_surface_is_exactly_five_get_routes(self) -> None:
        application = create_app()
        routes = {(route.path, frozenset(route.methods)) for route in application.routes if isinstance(route, APIRoute) and not route.path.startswith("/api/")}

        self.assertEqual(
            routes,
            {
                (LOCAL_OVERVIEW_PATH, frozenset({"GET"})),
                (LOCAL_NIGHT_DETAIL_PATH, frozenset({"GET"})),
                (LOCAL_NIGHT_DETAIL_SCRIPT_PATH, frozenset({"GET"})),
                (LOCAL_OVERVIEW_STYLES_PATH, frozenset({"GET"})),
                (LOCAL_OVERVIEW_SCRIPT_PATH, frozenset({"GET"})),
            },
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_generic_responses_render_recent_nights_trends_quality_and_paths(self) -> None:
        payload = self._populated_payload()
        rendered = unescape(self._render_with_node(payload))

        self.assertIn("PAP analysis", rendered)
        self.assertIn("Experiments are optional", rendered)
        for heading in ("Recent nights", "Longitudinal patterns", "Data quality", "Available analysis paths", "Evidence boundaries"):
            with self.subTest(heading=heading):
                self.assertIn(heading, rendered)
        for date in ("2026-09-09", "2026-09-08", "2026-09-07", "2026-09-06"):
            self.assertIn(date, rendered)
        self.assertIn("Mean Mask Pressure above EPAP", rendered)
        self.assertIn("Minute ventilation upper-tail ratio", rendered)
        self.assertIn("Structural data quality", rendered)
        self.assertIn("Signal data quality", rendered)
        self.assertIn("Optional comparison", rendered)
        self.assertIn("Open compatibility report", rendered)
        self.assertIn("analysis_workspace_not_complete", rendered)
        self.assertIn("wake_prerequisite_missing", rendered)
        self.assertIn("metric_input_missing", rendered)
        self.assertIn("Not evaluable", rendered)
        self.assertIn("Unavailable", rendered)
        self.assertIn('/nights/night%3Anew', rendered)
        self.assertEqual(rendered.count('<svg class="trend-chart"'), 1)
        self.assertEqual(rendered.count("<circle "), 3)
        self.assertEqual(rendered.count('<path class="trend-line"'), 1)
        self.assertNotIn("undefined", rendered)
        self.assertNotIn("NaN", rendered)
        self.assertNotIn("Infinity", rendered)
        self.assertNotIn("<canvas", rendered.lower())

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_unconfigured_api_responses_render_explicit_unavailable_state(self) -> None:
        with TestClient(create_app()) as client:
            payload = {
                "overview": client.get(ANALYSIS_OVERVIEW_PATH).json(),
                "nights": client.get(ANALYSIS_NIGHTS_PATH).json(),
                "trends": client.get(ANALYSIS_TRENDS_PATH).json(),
            }

        rendered = unescape(self._render_with_node(payload))

        self.assertIn("analysis_workspace_not_configured", rendered)
        self.assertIn("No recent nights are available", rendered)
        self.assertIn("No trend series are available", rendered)
        self.assertIn("Quality evidence is unavailable", rendered)
        self.assertIn("No experiment is linked, and none is required", rendered)
        self.assertGreaterEqual(rendered.count("Unavailable"), 7)
        self.assertNotIn('<svg class="trend-chart"', rendered)
        self.assertNotIn("undefined", rendered)
        self.assertNotIn("NaN", rendered)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_missing_trend_points_are_listed_and_never_connected_as_zero(self) -> None:
        payload = self._populated_payload()
        rendered = unescape(self._render_with_node(payload))

        self.assertIn("2026-09-08</time><span class=\"point-value empty-value\">Not evaluable", rendered)
        self.assertIn("2026-09-06</time><span class=\"point-value empty-value\">Unavailable", rendered)
        self.assertIn("gaps are not joined", rendered)
        self.assertNotIn(">0 <span>cm H₂O", rendered)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_renderer_escapes_api_text_and_has_a_visible_failure_state(self) -> None:
        payload = self._populated_payload()
        payload["overview"]["workspace"]["title"] = '<script data-test="unsafe">bad</script>'
        payload["overview"]["workspace"]["limitations"] = ["Local <evidence> only."]
        rendered = self._render_with_node(payload)
        error = self._render_error_with_node("<b>offline</b>")

        self.assertNotIn('<script data-test="unsafe">', rendered)
        self.assertIn("&lt;script data-test=&quot;unsafe&quot;&gt;bad&lt;/script&gt;", rendered)
        self.assertIn("Local &lt;evidence&gt; only.", rendered)
        self.assertNotIn("Local <evidence> only.", rendered)
        self.assertIn('role="alert"', error)
        self.assertIn("The PAP analysis overview could not be loaded.", error)
        self.assertIn("&lt;b&gt;offline&lt;/b&gt;", error)
        self.assertNotIn("<b>offline</b>", error)

    def test_asset_loader_is_allowlisted(self) -> None:
        self.assertEqual(OVERVIEW_ASSET_NAMES, frozenset({"night.html", "night.mjs", "overview.css", "overview.html", "overview.mjs"}))
        with self.assertRaises(ValueError):
            load_overview_asset("../server.py")

    @staticmethod
    def _render_with_node(payload: dict[str, object]) -> str:
        module_uri = files("pap_pilot.ui").joinpath("overview.mjs").as_uri()
        program = f'import {{renderOverview}} from {json.dumps(module_uri)}; let source = ""; for await (const chunk of process.stdin) source += chunk; const payload = JSON.parse(source); process.stdout.write(renderOverview(payload.overview, payload.nights, payload.trends));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), input=json.dumps(payload).encode("utf-8"), capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _render_error_with_node(message: str) -> str:
        module_uri = files("pap_pilot.ui").joinpath("overview.mjs").as_uri()
        program = f'import {{renderOverviewError}} from {json.dumps(module_uri)}; process.stdout.write(renderOverviewError({json.dumps(message)}));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _populated_payload() -> dict[str, object]:
        nights = [
            {
                "record_id": "analysis-night:night:new",
                "night_record_id": "night:new",
                "local_date": "2026-09-09",
                "availability": "partial",
                "session_record_ids": ["session:new"],
                "setting_record_ids": ["setting:new"],
                "event_record_ids": [],
                "signal_record_ids": ["signal:new"],
                "quality_report_ids": ["quality:new:structural", "quality:new:signal"],
                "metric_result_ids": ["metric:new:pressure"],
                "journal_entry_ids": [],
                "evidence_record_ids": ["evidence:quality:new:structural", "evidence:quality:new:signal"],
                "source_record_ids": ["night:new", "session:new"],
                "source_provenance_ids": ["provenance:new"],
                "reason_codes": ["one_or_more_evidence_items_unavailable"],
                "limitations": ["Evidence coverage is not a clinical judgment."],
                "record_version": 1,
            },
            {
                "record_id": "analysis-night:night:old",
                "night_record_id": "night:old",
                "local_date": "2026-09-08",
                "availability": "available",
                "session_record_ids": ["session:old"],
                "setting_record_ids": ["setting:old"],
                "event_record_ids": ["event:old"],
                "signal_record_ids": ["signal:old"],
                "quality_report_ids": ["quality:old:structural"],
                "metric_result_ids": ["metric:old:pressure"],
                "journal_entry_ids": ["journal:old"],
                "evidence_record_ids": ["evidence:quality:old:structural"],
                "source_record_ids": ["night:old", "session:old"],
                "source_provenance_ids": ["provenance:old"],
                "reason_codes": [],
                "limitations": ["Evidence coverage is not a clinical judgment."],
                "record_version": 1,
            },
        ]
        trends = [
            {
                "record_id": "trend:pressure",
                "metric_id": "mean_mask_pressure_above_epap",
                "label": "Mean Mask Pressure above EPAP",
                "unit": "cm H₂O",
                "availability": "partial",
                "points": [
                    {"night_record_id": "night:four", "local_date": "2026-09-06", "value": 2.0, "availability": "available", "source_record_ids": ["metric:four"], "source_provenance_ids": ["p:four"], "reason_codes": []},
                    {"night_record_id": "night:three", "local_date": "2026-09-07", "value": 2.4, "availability": "available", "source_record_ids": ["metric:three"], "source_provenance_ids": ["p:three"], "reason_codes": []},
                    {"night_record_id": "night:old", "local_date": "2026-09-08", "value": None, "availability": "not_evaluable", "source_record_ids": [], "source_provenance_ids": [], "reason_codes": ["metric_input_missing"]},
                    {"night_record_id": "night:new", "local_date": "2026-09-09", "value": 1.8, "availability": "available", "source_record_ids": ["metric:new"], "source_provenance_ids": ["p:new"], "reason_codes": []},
                ],
                "source_record_ids": ["metric:four", "metric:three", "metric:new"],
                "source_provenance_ids": ["p:four", "p:three", "p:new"],
                "reason_codes": ["one_or_more_points_unavailable"],
                "limitations": [],
                "record_version": 1,
            },
            {
                "record_id": "trend:ventilation",
                "metric_id": "minute_ventilation_upper_tail_ratio",
                "label": "Minute ventilation upper-tail ratio",
                "unit": "1",
                "availability": "partial",
                "points": [
                    {"night_record_id": "night:four", "local_date": "2026-09-06", "value": None, "availability": "unavailable", "source_record_ids": [], "source_provenance_ids": [], "reason_codes": ["metric_input_missing"]},
                    {"night_record_id": "night:new", "local_date": "2026-09-09", "value": None, "availability": "not_evaluable", "source_record_ids": [], "source_provenance_ids": [], "reason_codes": ["metric_input_missing"]},
                ],
                "source_record_ids": [],
                "source_provenance_ids": [],
                "reason_codes": ["metric_input_missing"],
                "limitations": [],
                "record_version": 1,
            },
        ]
        evidence = [
            {"record_id": "evidence:quality:new:structural", "kind": "quality", "label": "Structural data quality", "availability": "available", "night_record_ids": ["night:new"], "session_record_ids": ["session:new"], "source_record_ids": ["quality:new:structural"], "source_provenance_ids": ["provenance:new"], "reason_codes": ["clock_correction_integrity:pass:condition_not_observed"], "limitations": [], "record_version": 1},
            {"record_id": "evidence:quality:new:signal", "kind": "quality", "label": "Signal data quality", "availability": "not_evaluable", "night_record_ids": ["night:new"], "session_record_ids": ["session:new"], "source_record_ids": ["quality:new:signal"], "source_provenance_ids": ["provenance:new"], "reason_codes": ["likely_wake_breathing:insufficient_evidence:wake_prerequisite_missing"], "limitations": [], "record_version": 1},
        ]
        workspace = {
            "record_id": "analysis-workspace:test",
            "title": "PAP analysis",
            "availability": "partial",
            "nights": list(reversed(nights)),
            "trends": trends,
            "evidence": evidence,
            "resources": [],
            "experiments": [{"experiment_record_id": "experiment:optional", "label": "Optional comparison", "resource_id": "analysis:experiment:experiment:optional", "summary_record_id": "report:optional", "availability": "available", "source_record_ids": ["experiment:optional", "report:optional"], "source_provenance_ids": ["provenance:experiment"], "compatibility_fixture_id": "pap-pilot.ps-min-retrospective", "reason_codes": [], "limitations": ["Optional compatibility fixture."], "record_version": 1}],
            "source_record_ids": ["night:new", "night:old"],
            "source_provenance_ids": ["provenance:new", "provenance:old"],
            "reason_codes": ["analysis_workspace_not_complete"],
            "limitations": ["Analysis is advisory and does not change PAP-device settings.", "Missing data remains unavailable and is never converted to zero or imputed."],
            "schema_id": "pap-pilot.analysis-workspace",
            "schema_version": 1,
            "record_version": 1,
            "engine_version": "0.1.0",
        }
        return {
            "overview": {"format": "pap-pilot.analysis-workspace-json", "format_version": 1, "workspace": workspace},
            "nights": {"format": "pap-pilot.analysis-resource-json", "format_version": 1, "resource": {"resource_id": "analysis:nights", "kind": "night_collection", "target_record_id": workspace["record_id"], "availability": "partial", "reason_codes": ["one_or_more_nights_partial"], "record_version": 1}, "nights": nights},
            "trends": {"format": "pap-pilot.analysis-resource-json", "format_version": 1, "resource": {"resource_id": "analysis:trends", "kind": "trend_collection", "target_record_id": workspace["record_id"], "availability": "partial", "reason_codes": ["one_or_more_trends_incomplete"], "record_version": 1}, "trends": trends},
        }


if __name__ == "__main__":
    unittest.main()
