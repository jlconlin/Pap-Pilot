"""Focused browser-asset and rendering tests for the experiment overview."""

from html import unescape
from importlib.resources import files
import json
import re
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
    """Verify the overview and bounded waveform display are local and read-only."""

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

    def test_shell_loads_only_local_assets_and_contains_no_editing_surface(self) -> None:
        shell = load_overview_asset("overview.html")
        script = load_overview_asset("overview.mjs")
        combined = f"{shell}\n{script}".lower()

        self.assertIn('id="overview"', shell)
        self.assertIn('href="/assets/overview.css"', shell)
        self.assertIn('src="/assets/overview.mjs"', shell)
        self.assertIn("/api/v1/experiments/ps-min-2-to-1/summary", script)
        self.assertNotIn("http://", combined)
        self.assertNotIn("https://", combined)
        self.assertIn("display_contract_version", script)
        self.assertIn("<svg", script)
        for element in ("form", "input", "textarea", "select", "button", "canvas"):
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
    def test_preselected_waveforms_render_both_periods_with_units_and_evidence_links(self) -> None:
        with TestClient(create_app()) as client:
            payload = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()
        self._populate_waveforms(payload)

        rendered = self._render_with_node(json.dumps(payload).encode("utf-8"))

        self.assertEqual(rendered.count('class="interval-card interval-card-available"'), 2)
        self.assertIn('data-period="baseline"', rendered)
        self.assertIn('data-period="intervention"', rendered)
        self.assertEqual(rendered.count('<svg class="waveform-chart'), 6)
        self.assertEqual(rendered.count('class="waveform-trace"'), 6)
        self.assertIn('data-signal-kind="flow_rate" data-unit="L/min"', rendered)
        self.assertIn('data-signal-kind="mask_pressure" data-unit="cm H₂O"', rendered)
        self.assertIn('data-signal-kind="leak" data-unit="L/min"', rendered)
        self.assertIn("Supplied samples connected without smoothing", rendered)
        self.assertIn("Stored updates shown as steps", rendered)
        self.assertIn("raw-relative milliseconds", rendered)
        self.assertNotIn("unresolved", rendered)
        self.assertNotIn("Signal unavailable", rendered)
        evidence_targets = re.findall(r'href="#([^"]+)"', rendered)
        self.assertTrue(evidence_targets)
        for target in evidence_targets:
            self.assertIn(f'id="{target}"', rendered)
        for element in ("<form", "<input", "<button", "<canvas"):
            self.assertNotIn(element, rendered.lower())

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_missing_signal_inside_a_selected_interval_fails_visibly_without_a_trace(self) -> None:
        with TestClient(create_app()) as client:
            payload = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()
        self._populate_waveforms(payload, missing_baseline_leak=True)

        rendered = self._render_with_node(json.dumps(payload).encode("utf-8"))

        self.assertEqual(rendered.count('<svg class="waveform-chart'), 5)
        self.assertIn('class="waveform-panel waveform-panel-missing" data-signal-kind="leak"', rendered)
        self.assertIn("This signal excerpt was not supplied and no trace was inferred.", rendered)
        self.assertIn("signal_excerpt_missing", rendered)
        self.assertNotIn("undefined", rendered)
        self.assertNotIn("NaN", rendered)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_unplottable_signal_range_fails_locally_without_invalid_svg_coordinates(self) -> None:
        with TestClient(create_app()) as client:
            payload = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()
        self._populate_waveforms(payload)
        report = payload["report"]
        assert isinstance(report, dict)
        intervals = report["representative_intervals"]
        assert isinstance(intervals, list)
        baseline = intervals[0]
        assert isinstance(baseline, dict)
        signals = baseline["signals"]
        assert isinstance(signals, list)
        flow = signals[0]
        assert isinstance(flow, dict)
        flow["values"] = [1e308, -1e308, 1e308, -1e308, 1e308]

        rendered = self._render_with_node(json.dumps(payload).encode("utf-8"))

        self.assertEqual(rendered.count('<svg class="waveform-chart'), 5)
        self.assertIn("Signal unavailable", rendered)
        self.assertIn("cannot be plotted safely", rendered)
        self.assertNotIn("NaN", rendered)
        self.assertNotIn("Infinity", rendered)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused browser-renderer check.")
    def test_waveform_contract_rejects_wrong_units_and_oversized_excerpts(self) -> None:
        with TestClient(create_app()) as client:
            wrong_unit_payload = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()
            oversized_payload = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()
        self._populate_waveforms(wrong_unit_payload)
        self._populate_waveforms(oversized_payload)

        wrong_unit_signal = wrong_unit_payload["report"]["representative_intervals"][0]["signals"][0]
        wrong_unit_signal["unit"] = "mL/s"
        oversized_signal = oversized_payload["report"]["representative_intervals"][0]["signals"][0]
        oversized_signal["sample_times_ms"] = [1_000 + index for index in range(2_001)]
        oversized_signal["values"] = [float(index % 10) for index in range(2_001)]

        wrong_unit_rendered = self._render_with_node(json.dumps(wrong_unit_payload).encode("utf-8"))
        oversized_rendered = self._render_with_node(json.dumps(oversized_payload).encode("utf-8"))

        self.assertEqual(wrong_unit_rendered.count('<svg class="waveform-chart'), 5)
        self.assertIn("Flow Rate must retain its L/min unit.", wrong_unit_rendered)
        self.assertNotIn('data-unit="mL/s"', wrong_unit_rendered)
        self.assertEqual(oversized_rendered.count('<svg class="waveform-chart'), 5)
        self.assertIn("two to 2000 paired samples", oversized_rendered)

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
        module_uri = files("pap_pilot.ui").joinpath("overview.mjs").as_uri()
        program = f'import {{renderOverview}} from {json.dumps(module_uri)}; let source = ""; for await (const chunk of process.stdin) source += chunk; process.stdout.write(renderOverview(JSON.parse(source)));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), input=payload, capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _render_error_with_node(message: str) -> str:
        module_uri = files("pap_pilot.ui").joinpath("overview.mjs").as_uri()
        program = f'import {{renderOverviewError}} from {json.dumps(module_uri)}; process.stdout.write(renderOverviewError({json.dumps(message)}));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _populate_waveforms(payload: dict[str, object], *, missing_baseline_leak: bool = False) -> None:
        report = payload["report"]
        assert isinstance(report, dict)
        provenance = report["provenance"]
        assert isinstance(provenance, dict)
        provenance_ids = set(provenance["source_record_ids"])
        intervals = []
        for period_index, period in enumerate(("baseline", "intervention")):
            start_ms = 1_000 + period_index * 5_000
            end_ms = start_ms + 4_000
            interval_id = f"interval:{period}"
            night_id = f"night:{period}"
            session_id = f"session:{period}"
            signals = []
            signal_values = {
                "flow_rate": ("L/min", "uniform_waveform", (0.0, 18.0, -12.0, 22.0, -8.0)),
                "mask_pressure": ("cm H₂O", "uniform_waveform", (8.0, 12.0, 9.0, 13.0, 8.0)),
                "leak": ("L/min", "timed_updates", (2.0, 4.0, 3.0, 5.0)),
            }
            for signal_kind, (unit, representation, values) in signal_values.items():
                signal_id = f"signal:{period}:{signal_kind}"
                source_ids = [night_id, session_id, signal_id]
                if missing_baseline_leak and period == "baseline" and signal_kind == "leak":
                    signals.append({
                        "availability": "missing",
                        "reason_codes": ["signal_excerpt_missing"],
                        "representation": None,
                        "sample_times_ms": [],
                        "signal_kind": signal_kind,
                        "signal_record_id": None,
                        "source_record_ids": [night_id, session_id],
                        "unit": unit,
                        "values": [],
                    })
                    continue
                sample_times = [start_ms + offset for offset in ((0, 800, 1_600, 2_400, 3_200) if signal_kind != "leak" else (0, 1_200, 2_600, 3_800))]
                signals.append({
                    "availability": "available",
                    "reason_codes": [],
                    "representation": representation,
                    "sample_times_ms": sample_times,
                    "signal_kind": signal_kind,
                    "signal_record_id": signal_id,
                    "source_record_ids": source_ids,
                    "unit": unit,
                    "values": list(values),
                })
                provenance_ids.update(source_ids)
            interval_sources = [interval_id, night_id, session_id]
            provenance_ids.update(interval_sources)
            intervals.append({
                "availability": "available",
                "display_contract_version": 1,
                "end_ms": end_ms,
                "interval_record_id": interval_id,
                "period": period,
                "reason_codes": [],
                "signals": signals,
                "source_record_ids": interval_sources,
                "start_ms": start_ms,
            })
        provenance["source_record_ids"] = sorted(provenance_ids)
        report["representative_intervals"] = intervals


if __name__ == "__main__":
    unittest.main()
