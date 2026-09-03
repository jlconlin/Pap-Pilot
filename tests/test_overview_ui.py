"""Focused browser-asset and rendering tests for the experiment overview."""

from html import unescape
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from pap_pilot.api import (
    LOCAL_OVERVIEW_PATH,
    LOCAL_OVERVIEW_SCRIPT_PATH,
    LOCAL_OVERVIEW_STYLES_PATH,
    PS_MIN_EXPERIMENT_SUMMARY_PATH,
    create_app,
)
from pap_pilot.ui import OVERVIEW_ASSET_NAMES, load_overview_asset


class ExperimentOverviewTests(unittest.TestCase):
    """Verify the overview is packaged, API-fed, complete, and read-only."""

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

    def test_shell_loads_only_local_assets_and_contains_no_editing_or_waveform_surface(self) -> None:
        shell = load_overview_asset("overview.html")
        script = load_overview_asset("overview.mjs")
        combined = f"{shell}\n{script}".lower()

        self.assertIn('id="overview"', shell)
        self.assertIn('href="/assets/overview.css"', shell)
        self.assertIn('src="/assets/overview.mjs"', shell)
        self.assertIn("/api/v1/experiments/ps-min-2-to-1/summary", script)
        self.assertNotIn("http://", combined)
        self.assertNotIn("https://", combined)
        for element in ("form", "input", "textarea", "select", "button", "canvas", "svg"):
            with self.subTest(element=element):
                self.assertNotIn(f"<{element}", combined)

    def test_ui_surface_is_exactly_three_get_routes(self) -> None:
        application = create_app()
        routes = {(route.path, frozenset(route.methods)) for route in application.routes if isinstance(route, APIRoute) and not route.path.startswith("/api/")}

        self.assertEqual(
            routes,
            {
                (LOCAL_OVERVIEW_PATH, frozenset({"GET"})),
                (LOCAL_OVERVIEW_STYLES_PATH, frozenset({"GET"})),
                (LOCAL_OVERVIEW_SCRIPT_PATH, frozenset({"GET"})),
            },
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_api_report_renders_every_required_overview_section_and_missing_state(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH)
        report = response.json()["report"]
        rendered = unescape(self._render_with_node(response.content))

        self.assertIn(report["title"], rendered)
        self.assertIn(report["record_id"], rendered)
        self.assertIn("Not evaluable without fabrication", rendered)
        self.assertIn("Known setting change", rendered)
        self.assertIn("2<span>cm H₂O", rendered)
        self.assertIn("1<span>cm H₂O", rendered)
        for heading in ("Comparison periods", "Objective metrics", "Subjective outcomes", "Evidence reports", "Representative intervals", "Evaluation", "Evidence boundaries", "Missing inputs", "Limitations"):
            with self.subTest(heading=heading):
                self.assertIn(heading, rendered)
        for label in ("Mean Mask Pressure above EPAP", "Minute ventilation upper-tail ratio", "Remembered awakenings", "Sleep quality", "Morning energy", "Daytime tiredness", "Quality reports", "Confounder reports", "Adverse-effect reports"):
            with self.subTest(label=label):
                self.assertIn(label, rendered)
        for period in report["periods"]:
            self.assertIn(f"{period['night_count']}</div><p class=\"count-label\">retained nights", rendered)
            self.assertIn(period["reason_codes"][0], rendered)
        for statement in (*report["uncertainty"], *report["limitations"]):
            self.assertIn(statement, rendered)
        for missing_input in report["missing_inputs"]:
            self.assertIn(missing_input["description"], rendered)
        self.assertGreaterEqual(rendered.count("Not available"), 10)
        self.assertGreaterEqual(rendered.count("Not issued"), 3)
        self.assertNotIn("undefined", rendered)
        self.assertNotIn("NaN", rendered)
        self.assertNotIn("<canvas", rendered.lower())
        self.assertNotIn("<svg", rendered.lower())

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_renderer_escapes_report_text_and_has_a_visible_failure_state(self) -> None:
        with TestClient(create_app()) as client:
            payload = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()
        payload["report"]["title"] = '<script data-test="unsafe">bad</script>'
        rendered = self._render_with_node(json.dumps(payload).encode("utf-8"))
        error = self._render_error_with_node("<b>offline</b>")

        self.assertNotIn('<script data-test="unsafe">', rendered)
        self.assertIn("&lt;script data-test=&quot;unsafe&quot;&gt;bad&lt;/script&gt;", rendered)
        self.assertIn('role="alert"', error)
        self.assertIn("The experiment overview could not be loaded.", error)
        self.assertIn("&lt;b&gt;offline&lt;/b&gt;", error)
        self.assertNotIn("<b>offline</b>", error)

    def test_asset_loader_is_allowlisted(self) -> None:
        self.assertEqual(OVERVIEW_ASSET_NAMES, frozenset({"overview.css", "overview.html", "overview.mjs"}))
        with self.assertRaises(ValueError):
            load_overview_asset("../server.py")

    @staticmethod
    def _render_with_node(payload: bytes) -> str:
        module_uri = (Path(__file__).parents[1] / "src" / "pap_pilot" / "ui" / "overview.mjs").as_uri()
        program = f'import {{renderOverview}} from {json.dumps(module_uri)}; let source = ""; for await (const chunk of process.stdin) source += chunk; process.stdout.write(renderOverview(JSON.parse(source)));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), input=payload, capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _render_error_with_node(message: str) -> str:
        module_uri = (Path(__file__).parents[1] / "src" / "pap_pilot" / "ui" / "overview.mjs").as_uri()
        program = f'import {{renderOverviewError}} from {json.dumps(module_uri)}; process.stdout.write(renderOverviewError({json.dumps(message)}));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), capture_output=True, check=True)
        return result.stdout.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
