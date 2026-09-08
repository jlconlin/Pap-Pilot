# PAP Pilot

PAP Pilot is a local, single-user tool for reviewing PAP therapy evidence and evaluating controlled settings experiments. It reads OSCAR-normalized data, calculates deterministic metrics, keeps an append-only experiment history, and presents the results in a local web interface.

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

Without a workspace configuration, PAP Pilot loads a retained synthetic retrospective fixture. It is useful for checking the interface and report states, but it is not your OSCAR data and it does not automatically import anything. The local experiment history is stored in `pap_pilot.sqlite3` in the directory from which the command is started.

The overview can show experiment findings, evidence coverage, monitoring state, journal history, provenance, and explicit missing or not-evaluable states. Missing evidence is reported rather than silently inferred.

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
