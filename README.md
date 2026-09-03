# PAP Pilot

PAP Pilot is a local, single-user tool for independently analyzing OSCAR-normalized PAP data and evaluating controlled settings experiments. OSCAR remains the canonical data store; PAP Pilot's adapter is read-only, and its deterministic analysis engine is separate from OSCAR, the user interface, and any AI assistance.

## Development

Create an isolated environment, install the package, and run the smoke test:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python -m unittest discover --start-directory tests --verbose
```

The package includes a guarded schema-17 OSCAR adapter, versioned normalized engine records, deterministic experiment analysis, and a local read-only web application. Run it with `.venv/bin/pap-pilot-api`; it binds only to `127.0.0.1:8765`. Open `http://127.0.0.1:8765/` for the experiment overview. The service also exposes `GET /api/v1/health` and `GET /api/v1/experiments/ps-min-2-to-1/summary`. The overview renders bounded preselected waveform excerpts when the report supplies them and otherwise preserves the report's visible missing state. Editing and AI integration remain later work.
