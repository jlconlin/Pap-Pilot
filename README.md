# PAP Pilot

PAP Pilot is a local, single-user tool for independently analyzing OSCAR-normalized PAP data and evaluating controlled settings experiments. OSCAR remains the canonical data store; PAP Pilot's adapter is read-only, and its deterministic analysis engine is separate from OSCAR, the user interface, and any AI assistance.

PAP Pilot is licensed under the GNU General Public License, version 3.0 only (GPL-3.0-only). See [LICENSE](LICENSE).

## Development

Create an isolated environment, install the package, and run the smoke test:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python -m unittest discover --start-directory tests --verbose
```

The package includes a guarded schema-17 OSCAR adapter, versioned normalized engine records, deterministic experiment analysis, and a local web application. Run it with `.venv/bin/pap-pilot-api`; it binds only to `127.0.0.1:8765`. Open `http://127.0.0.1:8765/` for the experiment overview. Without a workspace configuration, the service intentionally shows the retained missing-evidence fixture and stores its history in `pap_pilot.sqlite3` in the current working directory.

To serve an evaluated retrospective workspace, first populate an existing `pap_pilot.sqlite3` through the bounded retrospective protocol and evidence intake, make a fixed disposable `oscar.db` copy while OSCAR is closed, and create a local ignored `pap-pilot-workspace.json` beside those files:

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

Paths are resolved relative to the configuration file. Session identifiers and interval bounds must be supplied explicitly; PAP Pilot does not detect a cohort or choose representative waveforms. Keep this configuration and both databases outside version control, then start `.venv/bin/pap-pilot-api --workspace-config /path/to/pap-pilot-workspace.json`. Startup rebuilds the deterministic report from the read-only OSCAR copy and the effective append-only history. A boundary correction appends both a correction event and its note without replacing the earlier event; restarting PAP Pilot replays that history and rebuilds the report. The overview preserves explicit missing states and remains local-only. General editing and AI integration remain later work.
