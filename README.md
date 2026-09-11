# PAP Pilot

PAP Pilot is a local, single-user tool for understanding PAP therapy data over time. It is being developed as a general analysis workspace for recent-night review, longitudinal trends, night-by-night evidence, signal quality, waveform and event inspection, subjective outcomes, and optional controlled settings experiments.

PAP Pilot is an analysis and decision-support prototype. It does not change PAP device settings, write to OSCAR, diagnose medical conditions, or send health data to a hosted AI service. OSCAR remains the canonical data store, and any settings change remains a manual decision for the user and their clinician.

## Run it

PAP Pilot requires Python 3.11 or newer. From the repository directory, create an environment and install the package:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[test]'
```

Start the local web application:

```bash
.venv/bin/pap-pilot-api
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) in a browser. The service binds only to loopback; it is not exposed to your network. Stop it with `Ctrl-C`.

You can check that it is running with:

```bash
curl http://127.0.0.1:8765/api/v1/health
```

## What the default run shows

Without a workspace configuration, the browser shows an explicit unavailable analysis workspace with the reason `analysis_workspace_not_configured`. PAP Pilot does not automatically locate or import OSCAR data, so an unconfigured dashboard must not be mistaken for an empty therapy history.

With a configured workspace, the landing page shows recent therapy nights, deterministic longitudinal trends, retained data-quality records, workspace limitations, and links to available local analysis resources. Open a night to inspect its sessions, observed settings, machine-labeled events, signal evidence, quality findings, and source links. Waveform views are limited to 2,000 exact samples from the first stored segment and explicitly disclose omitted samples; missing and not-evaluable values remain visible and are never plotted as zero. Experiments appear only as optional linked workflows.

The legacy synthetic PS Min report and its local append-only history remain available through the compatibility API under `/api/v1/experiments/ps-min-2-to-1/*`. That fixture is useful for regression checks, but it is not your OSCAR data. If its history routes are used, the local ledger is stored in `pap_pilot.sqlite3` in the directory from which the command is started.

## Generic read-only API

The configured application composes normalized nights, existing deterministic quality and metric results, replayed local journal entries, and optional experiment references into the generic analysis workspace. The current version exposes these GET-only resources:

- `/api/v1/analysis/overview`
- `/api/v1/analysis/nights`
- `/api/v1/analysis/nights/{night_record_id}`
- `/api/v1/analysis/trends`
- `/api/v1/analysis/trends/{trend_record_id}`
- `/api/v1/analysis/evidence/{evidence_record_id}`
- `/api/v1/analysis/experiments/{experiment_record_id}`

Night collections are ordered most recent first. With no workspace configuration, overview, night, and trend collections remain available as explicit `unavailable` responses with the reason `analysis_workspace_not_configured`; PAP Pilot does not search OSCAR or fabricate an empty result. The existing `/api/v1/experiments/ps-min-2-to-1/*` routes remain compatibility endpoints.

## Use a disposable OSCAR copy

Do not point PAP Pilot at a live OSCAR database while recovering or exploring your data. Close OSCAR, make a fixed disposable copy of its `oscar.db`, and keep the copy and PAP Pilot’s `pap_pilot.sqlite3` outside version control. PAP Pilot opens the configured OSCAR database in SQLite read-only mode and refuses unsupported or malformed workspaces, but the project still requires OSCAR to remain closed during reads.

An evaluated retrospective workspace requires a local JSON configuration containing the disposable OSCAR path, experiment database path, explicit session database IDs, and explicit representative intervals. Paths are relative to the configuration file. A minimal shape is:

```json
{
  "format": "pap-pilot.retrospective-workspace",
  "format_version": 1,
  "oscar_database_path": "oscar.db",
  "oscar_copy_is_fixed_and_disposable": true,
  "experiment_database_path": "pap_pilot.sqlite3",
  "selected_session_database_ids": [101, 102, 103, 104, 105, 106],
  "representative_intervals": [
    {"record_id": "selection:baseline", "period": "baseline", "session_database_id": 101, "start_ms": 1800000000000, "end_ms": 1800000000200, "signal_kinds": ["flow_rate", "mask_pressure", "leak_rate"]},
    {"record_id": "selection:intervention", "period": "intervention", "session_database_id": 104, "start_ms": 1800259200000, "end_ms": 1800259200200, "signal_kinds": ["flow_rate", "mask_pressure", "leak_rate"]}
  ]
}
```

Start the configured workspace with:

```bash
.venv/bin/pap-pilot-api --workspace-config /absolute/path/to/pap-pilot-workspace.json
```

PAP Pilot does not discover a cohort, choose representative waveforms, or overwrite earlier experiment events. The workspace must be prepared through the bounded retrospective protocol and evidence intake before it can produce an evaluated report.

## Current boundaries

- OSCAR access is local and read-only; OSCAR remains the canonical PAP-data store.
- The application never changes device settings or performs automatic therapy actions.
- Deterministic calculations and safety gates do not depend on the user interface or AI code.
- Hosted AI integration is deferred; no provider credential or health-data transmission is configured.
- The prototype is for one known user and is not a medical device or clinical decision system.

## Development

Run the test suite with:

```bash
.venv/bin/python -m unittest discover --start-directory tests --verbose
```

The package provides the `pap-pilot-api` console command. The source is under `src/pap_pilot`, tests are under `tests`, and validation notes and decisions are under `docs`.

PAP Pilot is licensed under the GNU General Public License, version 3.0 only (GPL-3.0-only). See [LICENSE](LICENSE).
