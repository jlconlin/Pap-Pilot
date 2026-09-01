# Official OSCAR Python demonstration result

**Run:** August 30, 2026 (America/Denver)

**Scope:** Run the official, unmodified Python waveform demonstrator against only a fresh protected disposable copy of the local OSCAR database. No live database access, demo modification, or adapter design was permitted.

## Artifact and input provenance

| Item | Verified identity |
|---|---|
| Official archive | `https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip` |
| Archive SHA-256 | `b5ef2878d73175b62e29a9fce8373de0e697c234130528005c3d32e3d6399ef8` |
| Demo member | `Notes/Waveform Demo/oscar_waveform_demo.py` |
| Demo SHA-256 | `835b9306f57e22372d4e79b709d1fb71846cbe91bee4ec41cbdcb8e8d247e2ad` |
| Specification member | `Notes/Waveform Demo/python_waveform_demo_spec.md` |
| Specification SHA-256 | `642229e105b2eca51491bc70e0d0a623fb0c2e23205224aacc4e7d427cdbae3e` |
| Installed OSCAR | 2.0.0 |
| Disposable database schema | 17, established in S04 |
| Demo-supported schema | 13, from `SUPPORTED_SCHEMA_VERSION` |

The archive and member hashes matched the S03 provenance record before the demo was run. The database copy was made only after OSCAR was confirmed closed and its WAL/SHM sidecars were absent. Source and copy byte counts and SHA-256 digests matched; the database digest and size are not retained here. The copy was then protected as file mode `0400` inside a mode-`0500` directory.

## Runtime environment

| Component | Version |
|---|---|
| Operating system | macOS 26.5.2, build 25F84, arm64 |
| Python | 3.13.1 |
| Python `sqlite3` runtime | SQLite 3.47.2 |
| pip | 24.3.1 |
| NumPy | 2.5.2 |
| Matplotlib | 3.11.1 |

The runtime was isolated outside the repository:

```bash
python3 -m venv <TEMP>/venv
<TEMP>/venv/bin/python -m pip install numpy==2.5.2 matplotlib==3.11.1
```

Resolved transitive packages were `contourpy==1.3.3`, `cycler==0.12.1`, `fonttools==4.63.0`, `kiwisolver==1.5.1`, `packaging==26.3`, `pillow==12.3.0`, `pyparsing==3.3.2`, `python-dateutil==2.9.0.post0`, and `six==1.17.0`.

## Sanitized command

The profile argument was a non-identifying sentinel. Schema checking occurs before profile lookup, and the result below confirms the sentinel was never used in a profile query.

```bash
MPLCONFIGDIR=<TEMP>/mplconfig \
PYTHONNOUSERSITE=1 \
<TEMP>/venv/bin/python \
<TEMP>/demo/oscar_waveform_demo.py \
<DISPOSABLE_DB>/oscar.db \
SANITIZED_PROFILE_NOT_REACHED
```

## Result

The command was run twice without changing the script or database. Both runs exited with status **1** at the first `schema_version` query. The repeat run's sanitized error was:

```text
Traceback (most recent call last):
  File "<TEMP>/demo/oscar_waveform_demo.py", line 517, in <module>
    sys.exit(main())
  File "<TEMP>/demo/oscar_waveform_demo.py", line 468, in main
    check_schema_version(conn)
  File "<TEMP>/demo/oscar_waveform_demo.py", line 87, in check_schema_version
    row = conn.execute(
sqlite3.OperationalError: attempt to write a readonly database
```

The demonstrator opens `file:{db_path}?mode=ro`. On this protected copy of the closed, formerly WAL-backed database, SQLite attempted an operation requiring write access while preparing the `SELECT MAX(version) FROM schema_version` statement. Copy protection correctly denied it. Consequently:

- No schema-version value was returned to the demo.
- The demo's intended schema-v13 versus schema-v17 mismatch exit was not reached.
- Profile resolution and all therapy-data queries were not reached.
- The demo produced no plot or therapy output.

S05 deliberately did not add `immutable=1`, create writable sidecars, alter permissions, or modify the demo to force later execution. Those would change the exact official execution being evaluated and belong to later guarded connection work.

## Post-run validation and cleanup

- The demo hash still matched the official artifact after both runs.
- The database-copy hash was unchanged after both runs.
- No WAL, SHM, or journal sidecar was created beside the copy.
- OSCAR remained closed and the live source was never passed to Python.
- The temporary archive, extracted files, virtual environment, Matplotlib cache, and disposable database copy were removed after verification.
- No OSCAR database, waveform, profile identifier, or other health data was added to the repository.

The official demonstration is therefore reproducibly **not runnable as published against this protected copy workflow**. This is a bounded result, not a reason to weaken the read-only boundary. S10 already owns implementation and testing of the project's guarded read-only connection.
