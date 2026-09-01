# PAP Pilot

PAP Pilot is a local, single-user tool for independently analyzing OSCAR-normalized PAP data and evaluating controlled settings experiments. OSCAR remains the canonical data store; PAP Pilot's adapter is read-only, and its deterministic analysis engine is separate from OSCAR, the user interface, and any AI assistance.

## Development

Create an isolated environment, install the package, and run the smoke test:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable .
.venv/bin/python -m unittest discover --start-directory tests --verbose
```

The package currently has no runtime dependencies. It includes a guarded schema-17 OSCAR adapter and versioned normalized engine records; adapter-to-model mapping, persistence, derived analysis, the web interface, and AI integration remain later work.
