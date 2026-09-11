"""Protected end-to-end tests for the configured retrospective localhost UI."""

from contextlib import closing
from importlib.resources import files
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from pap_pilot.adapter import OscarCohortSelection, extract_normalized_oscar_cohort
from pap_pilot.adapter._uniform_waveform import _qt_iso3309_checksum
from pap_pilot.api import (
    ANALYSIS_EVIDENCE_DETAIL_PATH,
    ANALYSIS_NIGHT_DETAIL_PATH,
    ANALYSIS_NIGHTS_PATH,
    ANALYSIS_OVERVIEW_PATH,
    ANALYSIS_TRENDS_PATH,
    PS_MIN_BOUNDARY_CORRECTION_PATH,
    PS_MIN_EXPERIMENT_HISTORY_PATH,
    PS_MIN_EXPERIMENT_SUMMARY_PATH,
    create_configured_app,
    main,
)
from pap_pilot.engine import (
    ExperimentStore,
    RetrospectiveEvidenceReportStatus,
    reconstruct_ps_min_experiment_fixture,
    record_retrospective_protocol,
    record_retrospective_user_evidence,
)
from pap_pilot.workflow import (
    RETROSPECTIVE_WORKSPACE_CONFIGURATION_FORMAT,
    RETROSPECTIVE_WORKSPACE_CONFIGURATION_VERSION,
    RetrospectiveWorkspaceConfigurationError,
    load_retrospective_workspace,
)
from tests.test_retrospective_evaluation import (
    _BOUNDARY_MS,
    _DAY_MS,
    _SESSION_DURATION_MS,
    _START_MS,
    _generic_cohort,
    _journal_inputs,
    _proposal,
    _protocol,
)
from tests import test_session_summary


class RetrospectiveLocalWorkspaceTests(unittest.TestCase):
    """Trace selected OSCAR rows through restart-safe API and UI rendering."""

    def setUp(self) -> None:
        source_fixture = test_session_summary.SessionSummaryTests(
            methodName="test_extracts_deterministic_session_summary_with_provenance"
        )
        source_fixture.setUp()
        self.addCleanup(source_fixture.doCleanups)
        self.oscar_path = source_fixture.database_path
        self.root = self.oscar_path.parent
        self.experiment_path = self.root / "pap_pilot.sqlite3"
        self.configuration_path = self.root / "pap-pilot-workspace.json"
        self.session_ids = tuple(range(1, 7))
        self._replace_source_with_six_nights()
        cohort = extract_normalized_oscar_cohort(
            self.oscar_path,
            OscarCohortSelection(self.session_ids),
            trusted_immutable_copy=True,
        )
        generic_cohort = _generic_cohort(cohort)
        fixture = reconstruct_ps_min_experiment_fixture()
        with ExperimentStore(self.experiment_path) as store:
            store.create_experiment(fixture.experiment)
            store.append_events(fixture.history)
            record_retrospective_protocol(
                store,
                fixture.experiment.record_id,
                generic_cohort,
                _protocol(fixture, _proposal(fixture, generic_cohort)),
            )
            record_retrospective_user_evidence(
                store,
                fixture.experiment.record_id,
                generic_cohort,
                _journal_inputs(generic_cohort),
            )
        self._write_configuration()
        self.oscar_bytes = self.oscar_path.read_bytes()
        self.oscar_path.chmod(0o400)

    def test_configured_app_links_selected_oscar_nights_to_every_ui_section(self) -> None:
        workspace = load_retrospective_workspace(self.configuration_path)
        with TestClient(create_configured_app(self.configuration_path)) as client:
            summary_response = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH)
            history_response = client.get(PS_MIN_EXPERIMENT_HISTORY_PATH)
            analysis_overview_response = client.get(ANALYSIS_OVERVIEW_PATH)
            analysis_nights_response = client.get(ANALYSIS_NIGHTS_PATH)
            analysis_trends_response = client.get(ANALYSIS_TRENDS_PATH)
            recent_night = workspace.analysis_workspace.nights[-1]
            analysis_night_response = client.get(ANALYSIS_NIGHT_DETAIL_PATH.format(night_record_id=recent_night.night_record_id))
            quality_id = next(identifier for identifier in recent_night.evidence_record_ids if identifier.startswith("analysis-evidence:quality:"))
            quality_evidence_response = client.get(ANALYSIS_EVIDENCE_DETAIL_PATH.format(evidence_record_id=quality_id))

        report = summary_response.json()["report"]
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(
            workspace.report.evaluation_status,
            RetrospectiveEvidenceReportStatus.EVALUATED,
        )
        self.assertEqual(report["evaluation_status"], "evaluated")
        self.assertEqual([value["night_count"] for value in report["periods"]], [3, 3])
        self.assertTrue(all(value["availability"] == "available" for value in report["objective_metrics"]))
        self.assertTrue(all(value["availability"] == "available" for value in report["subjective_outcomes"]))
        self.assertTrue(
            all(
                report[key]["availability"] == "available"
                for key in (
                    "quality_evidence",
                    "confounder_evidence",
                    "adverse_effect_evidence",
                )
            )
        )
        self.assertEqual(report["classification"]["classification"], "clear_improvement")
        self.assertEqual(report["classification"]["action"], "keep")
        self.assertEqual(report["missing_inputs"], [])
        self.assertEqual(
            [value["availability"] for value in report["representative_intervals"]],
            ["available", "available"],
        )
        self.assertEqual(
            [signal["availability"] for interval in report["representative_intervals"] for signal in interval["signals"]],
            ["available", "available", "missing", "available", "available", "missing"],
        )
        source_ids = set(report["provenance"]["source_record_ids"])
        self.assertTrue({f"sessions.id:{value}" for value in self.session_ids}.issubset(source_ids))
        self.assertGreater(len(history_response.json()["history"]), 2)
        analysis_overview = analysis_overview_response.json()["workspace"]
        analysis_nights = analysis_nights_response.json()["nights"]
        analysis_trends = analysis_trends_response.json()["trends"]
        self.assertEqual(analysis_overview["record_id"], workspace.analysis_workspace.record_id)
        self.assertEqual(len(analysis_nights), 6)
        self.assertEqual(len(analysis_trends), 2)
        self.assertTrue(all(len(value["metric_result_ids"]) == 2 for value in analysis_nights))
        self.assertTrue(all(len(value["journal_entry_ids"]) == 1 for value in analysis_nights))
        analysis_night = analysis_night_response.json()["night"]
        quality_evidence = quality_evidence_response.json()["evidence"]
        self.assertEqual(analysis_nights[0]["night_record_id"], analysis_night["night_record_id"])
        self.assertEqual(quality_evidence["kind"], "quality")
        self.assertTrue(quality_evidence["source_provenance_ids"])
        self.assertEqual(self.oscar_path.read_bytes(), self.oscar_bytes)

        if shutil.which("node"):
            rendered = self._render_with_node(
                analysis_overview_response.content,
                analysis_nights_response.content,
                analysis_trends_response.content,
            )
            for heading in (
                "Recent nights",
                "Longitudinal patterns",
                "Data quality",
                "Available analysis paths",
                "Evidence boundaries",
            ):
                self.assertIn(heading, rendered)
            self.assertEqual(rendered.count('<svg class="trend-chart'), 2)
            self.assertEqual(rendered.count('class="night-card"'), 6)
            self.assertIn("Experiments are optional", rendered)
            self.assertIn("PS Min 2 to 1 retrospective compatibility experiment", rendered)
            self.assertIn("Open compatibility report", rendered)
            for label in ("Mean Mask Pressure above EPAP", "Minute ventilation upper-tail ratio", "Structural data quality", "Signal data quality"):
                self.assertIn(label, rendered)
            self.assertNotIn('id="boundary-correction-form"', rendered)
            self.assertNotIn("undefined", rendered)
            self.assertNotIn("NaN", rendered)

    def test_effective_history_and_rebuilt_report_persist_across_restart(self) -> None:
        first_application = create_configured_app(self.configuration_path)
        with TestClient(first_application) as client:
            before = client.get(PS_MIN_EXPERIMENT_HISTORY_PATH).json()
            correction = client.post(
                PS_MIN_BOUNDARY_CORRECTION_PATH,
                json={
                    "corrected_event_id": before["effective_boundary"]["record_id"],
                    "applied_at_ms": _BOUNDARY_MS - 1_000,
                    "note": "Synthetic restart-persistence check.",
                },
            )
            old_report_id = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()["report"]["record_id"]
        self.assertEqual(correction.status_code, 201)

        restarted_application = create_configured_app(self.configuration_path)
        with TestClient(restarted_application) as client:
            after = client.get(PS_MIN_EXPERIMENT_HISTORY_PATH).json()
            rebuilt_report_id = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()["report"]["record_id"]

        self.assertEqual(after["effective_boundary"]["applied_at_ms"], _BOUNDARY_MS - 1_000)
        self.assertEqual(len(after["history"]), len(before["history"]) + 2)
        self.assertIn("Synthetic restart-persistence check.", {value.get("note") for value in after["history"]})
        self.assertNotEqual(rebuilt_report_id, old_report_id)
        self.assertEqual(self.oscar_path.read_bytes(), self.oscar_bytes)

    def test_command_selects_configured_app_without_relaxing_loopback_binding(self) -> None:
        with patch("pap_pilot.api.server.uvicorn.run") as run:
            main(("--workspace-config", str(self.configuration_path)))

        application = run.call_args.args[0]
        self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")
        with TestClient(application) as client:
            self.assertEqual(
                client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH).json()["report"]["evaluation_status"],
                "evaluated",
            )

    def test_configuration_refuses_a_source_without_the_disposable_copy_assertion(self) -> None:
        value = json.loads(self.configuration_path.read_text(encoding="utf-8"))
        value["oscar_copy_is_fixed_and_disposable"] = False
        self.configuration_path.write_text(json.dumps(value), encoding="utf-8")

        with self.assertRaisesRegex(
            RetrospectiveWorkspaceConfigurationError,
            "fixed disposable copy",
        ):
            load_retrospective_workspace(self.configuration_path)

    def _replace_source_with_six_nights(self) -> None:
        with closing(sqlite3.connect(self.oscar_path)) as connection:
            connection.executescript(
                """
                DELETE FROM respiratory_events;
                DELETE FROM event_data;
                DELETE FROM event_lists;
                DELETE FROM session_settings;
                DELETE FROM sessions;
                CREATE TABLE device_time_corrections (
                    id INTEGER PRIMARY KEY,
                    machine_id INTEGER NOT NULL,
                    date_from TEXT NOT NULL,
                    date_to TEXT,
                    type TEXT NOT NULL,
                    offset_ms INTEGER,
                    c0_ms INTEGER,
                    c1 REAL,
                    reason TEXT,
                    applied_at TEXT NOT NULL,
                    undone_at TEXT
                );
                """
            )
            for index, session_id in enumerate(self.session_ids):
                start_ms = _START_MS + index * _DAY_MS
                end_ms = start_ms + _SESSION_DURATION_MS
                ps_min = 2.0 if index < 3 else 1.0
                pressure = 13.0 if index < 3 else 12.5
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, 7_000 + session_id, 10, start_ms, end_ms, _SESSION_DURATION_MS, 1, 0, 0, 0),
                )
                connection.executemany(
                    "INSERT INTO session_settings VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        (session_id, 1, 101, 6.0, "numeric", None),
                        (session_id, 1, 102, 7.0, "numeric", None),
                        (session_id, 1, 103, 10.0, "numeric", None),
                        (session_id, 1, 104, ps_min, "numeric", None),
                        (session_id, 1, 105, 5.0, "numeric", None),
                        (session_id, 1, 106, 15.0, "numeric", None),
                    ),
                )
                self._insert_signals(connection, index, session_id, start_ms, end_ms, pressure)
            connection.commit()

    @staticmethod
    def _insert_signals(
        connection: sqlite3.Connection,
        index: int,
        session_id: int,
        start_ms: int,
        end_ms: int,
        pressure: float,
    ) -> None:
        sample_count = _SESSION_DURATION_MS // 40
        flow_data = struct.pack(f"<{sample_count}h", *((100,) * sample_count))
        pressure_raw = int(pressure * 10)
        pressure_data = struct.pack(f"<{sample_count}h", *((pressure_raw,) * sample_count))
        leak_data = struct.pack("<2h", 5, 5)
        leak_times = struct.pack("<2I", 0, _SESSION_DURATION_MS)
        base = 1_000 + index * 10
        rows = (
            (base + 1, session_id, 1, 301, 0, 0, start_ms, end_ms, sample_count, 40.0, 0.1, 0.0, 10.0, 10.0, "L/M", 0, None, None, len(flow_data), len(flow_data)),
            (base + 2, session_id, 1, 302, 0, 0, start_ms, end_ms, sample_count, 40.0, 0.1, 0.0, pressure, pressure, "cmH2O", 0, None, None, len(pressure_data), len(pressure_data)),
            (base + 3, session_id, 1, 303, 0, 1, start_ms, end_ms, 2, 0.0, 1.0, 0.0, 5.0, 5.0, None, 0, None, None, len(leak_data) + len(leak_times), len(leak_data) + len(leak_times)),
        )
        connection.executemany(
            "INSERT INTO event_lists VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO event_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (base + 4, base + 1, flow_data, None, None, None, None, None, 0, _qt_iso3309_checksum(flow_data)),
                (base + 5, base + 2, pressure_data, None, None, None, None, None, 0, _qt_iso3309_checksum(pressure_data)),
                (base + 6, base + 3, leak_data, None, None, None, leak_times, None, 0, _qt_iso3309_checksum(leak_data)),
            ),
        )

    def _write_configuration(self) -> None:
        value = {
            "format": RETROSPECTIVE_WORKSPACE_CONFIGURATION_FORMAT,
            "format_version": RETROSPECTIVE_WORKSPACE_CONFIGURATION_VERSION,
            "oscar_database_path": self.oscar_path.name,
            "oscar_copy_is_fixed_and_disposable": True,
            "experiment_database_path": self.experiment_path.name,
            "selected_session_database_ids": list(self.session_ids),
            "representative_intervals": [
                {
                    "record_id": "selection:configured:baseline",
                    "period": "baseline",
                    "session_database_id": 1,
                    "start_ms": _START_MS,
                    "end_ms": _START_MS + 200,
                    "signal_kinds": ["flow_rate", "mask_pressure", "leak_rate"],
                },
                {
                    "record_id": "selection:configured:intervention",
                    "period": "intervention",
                    "session_database_id": 4,
                    "start_ms": _START_MS + 3 * _DAY_MS,
                    "end_ms": _START_MS + 3 * _DAY_MS + 200,
                    "signal_kinds": ["flow_rate", "mask_pressure", "leak_rate"],
                },
            ],
        }
        self.configuration_path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def _render_with_node(overview_payload: bytes, nights_payload: bytes, trends_payload: bytes) -> str:
        module_uri = files("pap_pilot.ui").joinpath("overview.mjs").as_uri()
        program = f'import {{renderOverview}} from {json.dumps(module_uri)}; let source = ""; for await (const chunk of process.stdin) source += chunk; const payload = JSON.parse(source); process.stdout.write(renderOverview(payload.overview, payload.nights, payload.trends));'
        result = subprocess.run(
            ("node", "--input-type=module", "--eval", program),
            input=json.dumps({"overview": json.loads(overview_payload), "nights": json.loads(nights_payload), "trends": json.loads(trends_payload)}).encode("utf-8"),
            capture_output=True,
            check=True,
        )
        return result.stdout.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
