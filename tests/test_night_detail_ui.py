"""Focused S52 tests for generic night evidence composition, API, and rendering."""

from dataclasses import replace
from html import unescape
from importlib.resources import files
import json
import shutil
import subprocess
import unittest

from fastapi.testclient import TestClient

from pap_pilot.api import ANALYSIS_NIGHT_DETAIL_PATH, LOCAL_NIGHT_DETAIL_PATH, LOCAL_NIGHT_DETAIL_SCRIPT_PATH, create_app
from pap_pilot.engine import EventRecord, SignalRecord, SignalRepresentation, evaluate_signal_quality, evaluate_structural_quality
from pap_pilot.workflow import ANALYSIS_NIGHT_SIGNAL_PREVIEW_MAX_SAMPLES, ANALYSIS_NIGHT_SIGNAL_PREVIEW_SELECTION, compose_analysis_night_details, compose_analysis_workspace
from pap_pilot.ui import load_overview_asset
from tests.test_retrospective_evaluation import _cohort


class NightDetailUiTests(unittest.TestCase):
    """Cover populated, missing, and poor-quality evidence without a PS Min workflow."""

    @classmethod
    def setUpClass(cls) -> None:
        source_night = _cohort().nights[0]
        source_session = source_night.sessions[0]
        large_leak = EventRecord(
            record_id="event:generic-large-leak",
            event_kind="large_leak",
            start_time_ms=source_session.start_time_ms + 1_000,
            duration_ms=30_000,
            provenance=source_session.provenance,
        )
        missing_signal = SignalRecord(
            record_id="signal:generic-oxygen-missing",
            signal_kind="oxygen_saturation",
            unit="%",
            representation=SignalRepresentation.TIMED_UPDATES,
            segments=(),
            provenance=source_session.provenance,
            value_semantics="Stored oxygen saturation updates",
        )
        session = replace(source_session, events=(large_leak,), signals=(*source_session.signals, missing_signal))
        cls.night = replace(source_night, sessions=(session,))
        cls.structural = evaluate_structural_quality(
            cls.night,
            required_signal_kinds=("flow_rate", "mask_pressure", "oxygen_saturation"),
            require_flow_pressure_alignment=True,
        )
        cls.signal_quality = evaluate_signal_quality(session)
        cls.details = compose_analysis_night_details(
            (cls.night,),
            structural_quality_reports=(cls.structural,),
            signal_quality_reports=(cls.signal_quality,),
        )
        cls.workspace = compose_analysis_workspace(
            (cls.night,),
            structural_quality_reports=(cls.structural,),
            signal_quality_reports=(cls.signal_quality,),
        )

    def test_composition_preserves_populated_missing_and_poor_quality_evidence(self) -> None:
        detail = self.details[0]
        flow = next(value for value in detail.signals if value.signal_kind == "flow_rate")
        missing = next(value for value in detail.signals if value.signal_kind == "oxygen_saturation")
        flagged = next(value for value in detail.quality_findings if value.reason_code == "machine_large_leak_span")
        insufficient = next(value for value in detail.quality_findings if value.reason_code == "unsupported_signal_contract")

        self.assertEqual(detail.settings_availability.value, "available")
        self.assertEqual(len(detail.settings), 6)
        self.assertEqual(detail.events_availability.value, "available")
        self.assertEqual(detail.events[0].event_kind, "large_leak")
        self.assertEqual(detail.signals_availability.value, "partial")
        self.assertEqual(flow.displayed_sample_count, ANALYSIS_NIGHT_SIGNAL_PREVIEW_MAX_SAMPLES)
        self.assertEqual(len(flow.sample_times_ms), ANALYSIS_NIGHT_SIGNAL_PREVIEW_MAX_SAMPLES)
        self.assertEqual(len(flow.values), ANALYSIS_NIGHT_SIGNAL_PREVIEW_MAX_SAMPLES)
        self.assertGreater(flow.omitted_sample_count, 0)
        self.assertEqual(flow.preview_selection, ANALYSIS_NIGHT_SIGNAL_PREVIEW_SELECTION)
        self.assertEqual(missing.availability.value, "unavailable")
        self.assertEqual(missing.reason_codes, ("signal_samples_unavailable",))
        self.assertEqual((flagged.status, flagged.impact), ("flagged", "exclude_interval"))
        self.assertEqual((insufficient.status, insufficient.impact), ("insufficient_evidence", "block_requested_analysis"))
        self.assertEqual(detail.quality_availability.value, "partial")
        self.assertTrue(set(flow.source_record_ids).issubset(detail.source_record_ids))
        self.assertTrue(set(flagged.source_record_ids).issubset(detail.source_record_ids))
        self.assertTrue(set(flow.source_provenance_ids).issubset(detail.source_provenance_ids))
        self.assertTrue(detail.provenance)

    def test_composition_is_deterministic_and_rejects_unresolved_quality(self) -> None:
        repeated = compose_analysis_night_details(
            (self.night,),
            structural_quality_reports=(self.structural,),
            signal_quality_reports=(self.signal_quality,),
        )
        self.assertEqual(repeated, self.details)

        unrelated = replace(self.structural, night_record_id="night:unresolved")
        with self.assertRaisesRegex(ValueError, "resolve to a detail night"):
            compose_analysis_night_details((self.night,), structural_quality_reports=(unrelated,))

    def test_api_freezes_detail_and_serves_only_known_night_pages(self) -> None:
        with TestClient(create_app(analysis_workspace=self.workspace, analysis_night_details=self.details)) as client:
            response = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=self.night.record_id))
            page = client.get(LOCAL_NIGHT_DETAIL_PATH.format(night_record_id=self.night.record_id))
            script = client.get(LOCAL_NIGHT_DETAIL_SCRIPT_PATH)
            missing_page = client.get(LOCAL_NIGHT_DETAIL_PATH.format(night_record_id="night:unknown"))

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["resource"]["kind"], "night_detail")
        self.assertEqual(payload["night"]["night_record_id"], self.night.record_id)
        self.assertEqual(payload["detail"]["schema_id"], "pap-pilot.analysis-night-detail")
        self.assertEqual(len(payload["detail"]["settings"]), 6)
        self.assertEqual(len(next(value for value in payload["detail"]["signals"] if value["signal_kind"] == "flow_rate")["values"]), 2_000)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.text, load_overview_asset("night.html"))
        self.assertIn('id="night-detail"', page.text)
        self.assertEqual(script.status_code, 200)
        self.assertEqual(script.text, load_overview_asset("night.mjs"))
        self.assertIn("connect-src 'self'", page.headers["content-security-policy"])
        self.assertEqual(script.headers["cache-control"], "no-store")
        self.assertEqual(missing_page.status_code, 404)
        self.assertEqual(self._non_get_statuses(create_app(analysis_workspace=self.workspace, analysis_night_details=self.details)), {405})

    def test_workspace_only_app_returns_an_explicit_unavailable_detail(self) -> None:
        with TestClient(create_app(analysis_workspace=self.workspace)) as client:
            payload = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=self.night.record_id)).json()

        self.assertEqual(payload["detail"]["availability"], "unavailable")
        self.assertEqual(payload["detail"]["reason_codes"], ["night_detail_source_not_configured"])
        self.assertEqual(payload["detail"]["signals"], [])

    def test_api_rejects_detail_that_does_not_match_its_workspace_links(self) -> None:
        mismatched = replace(self.details[0], local_date="2099-01-01")
        with self.assertRaisesRegex(ValueError, "workspace local date"):
            create_app(analysis_workspace=self.workspace, analysis_night_details=(mismatched,))

    def test_api_rejects_a_preview_over_the_fixed_sample_limit(self) -> None:
        detail = self.details[0]
        flow = next(value for value in detail.signals if value.signal_kind == "flow_rate")
        oversized_flow = replace(
            flow,
            sample_times_ms=(*flow.sample_times_ms, flow.sample_times_ms[-1] + 40.0),
            values=(*flow.values, flow.values[-1]),
            displayed_sample_count=flow.displayed_sample_count + 1,
            omitted_sample_count=flow.omitted_sample_count - 1,
        )
        oversized = replace(detail, signals=tuple(oversized_flow if value is flow else value for value in detail.signals))
        with self.assertRaisesRegex(ValueError, "bounded sample-count contract"):
            create_app(analysis_workspace=self.workspace, analysis_night_details=(oversized,))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused night renderer check.")
    def test_renderer_shows_populated_missing_and_poor_quality_evidence(self) -> None:
        with TestClient(create_app(analysis_workspace=self.workspace, analysis_night_details=self.details)) as client:
            payload = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=self.night.record_id)).json()

        rendered = unescape(self._render_with_node(payload))

        for heading in ("Therapy sessions", "Observed settings", "Machine-labeled events", "Signal evidence", "Data-quality findings", "Sources and provenance", "Evidence boundaries"):
            self.assertIn(heading, rendered)
        for value in ("ps_min", "Large Leak", "Flow Rate", "Oxygen Saturation", "Missing Required Signal", "machine_large_leak_span"):
            self.assertIn(value, rendered)
        self.assertIn("2,000 exact samples", rendered)
        self.assertIn("2000</strong> displayed samples", rendered)
        self.assertIn("7000</strong> omitted samples", rendered)
        self.assertIn("signal_samples_unavailable", rendered)
        self.assertIn("Insufficient evidence", rendered)
        self.assertIn("Blocks requested analysis", rendered)
        self.assertIn("Exclude interval", rendered)
        self.assertIn("source-record-", rendered)
        self.assertIn("source-provenance-", rendered)
        self.assertIn('<polyline class="waveform-line"', rendered)
        self.assertIn('class="timed-update-point"', rendered)
        self.assertNotIn("undefined", rendered)
        self.assertNotIn("NaN", rendered)
        self.assertNotIn("Infinity", rendered)
        self.assertNotIn("<canvas", rendered.lower())

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the focused night renderer check.")
    def test_renderer_escapes_evidence_text_and_has_a_visible_failure_state(self) -> None:
        with TestClient(create_app(analysis_workspace=self.workspace, analysis_night_details=self.details)) as client:
            payload = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=self.night.record_id)).json()
        payload["detail"]["settings"][0]["name"] = '<script data-test="unsafe">bad</script>'
        rendered = self._render_with_node(payload)
        error = self._render_error_with_node("<b>offline</b>")

        self.assertIn("&lt;script data-test=&quot;unsafe&quot;&gt;bad&lt;/script&gt;", rendered)
        self.assertNotIn('<script data-test="unsafe">', rendered)
        self.assertIn('role="alert"', error)
        self.assertIn("This therapy-night record could not be loaded.", error)
        self.assertIn("&lt;b&gt;offline&lt;/b&gt;", error)
        self.assertNotIn("<b>offline</b>", error)

    @staticmethod
    def _non_get_statuses(application) -> set[int]:
        path = LOCAL_NIGHT_DETAIL_PATH.format(night_record_id="night:0")
        with TestClient(application) as client:
            return {client.request(method, path).status_code for method in ("POST", "PUT", "PATCH", "DELETE")}

    @staticmethod
    def _render_with_node(payload: dict[str, object]) -> str:
        module_uri = files("pap_pilot.ui").joinpath("night.mjs").as_uri()
        program = f'import {{renderNightDetail}} from {json.dumps(module_uri)}; let source = ""; for await (const chunk of process.stdin) source += chunk; process.stdout.write(renderNightDetail(JSON.parse(source)));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), input=json.dumps(payload).encode("utf-8"), capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    @staticmethod
    def _render_error_with_node(message: str) -> str:
        module_uri = files("pap_pilot.ui").joinpath("night.mjs").as_uri()
        program = f'import {{renderNightDetailError}} from {json.dumps(module_uri)}; process.stdout.write(renderNightDetailError({json.dumps(message)}));'
        result = subprocess.run(("node", "--input-type=module", "--eval", program), capture_output=True, check=True)
        return result.stdout.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
