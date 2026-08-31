# PAP Pilot — session handoff

**Updated:** August 31, 2026
**Governing plan:** `Plan.md`
**Current sprint:** None — S10 completed; stopped before S11
**Next sprint:** S11 — Extract one session summary

## Current state

- The Python application scaffold now uses a `src` layout with importable `pap_pilot`, `pap_pilot.adapter`, and `pap_pilot.engine` packages.
- `pyproject.toml` defines an installable, dependency-free Python package, and `README.md` documents the isolated editable-install and smoke-test commands.
- The adapter and deterministic engine are separate package namespaces; no database extraction, web UI, or AI implementation has begun.
- `pap_pilot.adapter.open_oscar_database` opens SQLite through a `mode=ro` URI, enables `query_only`, begins an explicit read transaction, validates schema identity, and always closes the connection.
- Schema version 17 is the only supported OSCAR schema; missing metadata and all other versions fail before the connection is exposed to extraction code.
- `Plan.md` is authoritative: Part I governs the personal prototype and Part II retains deferred future-product requirements.
- The former prototype and product-plan files have been consolidated into `Plan.md` and removed from the working tree.
- The large milestones have been decomposed into short, dependency-ordered sprints in `SPRINTS.md`.
- `Plan.md` contains milestone outcome gates but no implementation task list; `SPRINTS.md` alone governs sprint order and status.
- Repository-wide continuation and safety rules are in `AGENTS.md`.
- The approved working display name is **PAP Pilot**, written as two words and pronounced “P-A-P Pilot.”
- Approved identifiers are `pap-pilot` for the technical slug and command, `pap_pilot` for the Python package, and `pap_pilot.sqlite3` for the local database.
- `docs/decisions/0001-working-name.md` records the accepted decision and its advisory-use rationale.
- Exploratory image sheets and their generation prompts are preserved in `docs/branding/concepts/`; no final logo or visual identity has been selected.
- The local Git repository has clean, resumable planning checkpoints on `main`.
- `.gitignore` excludes operating-system/editor state, Python environments and generated files, local credentials, SQLite databases, raw EDF files, and OSCAR data directories while allowing `.env.example` to be tracked.
- No OSCAR database, raw therapy file, local credential file, or other sensitive/local data is tracked or appears by a sensitive-data filename pattern in reachable Git history.
- `docs/research/oscar-2-source-materials.md` records the official OSCAR 2.0.1 SQL Notes bundle and Python waveform demonstrator with source URLs, retrieval metadata, exact archive paths, and SHA-256 checksums.
- The official 2.0.1 Notes bundle's SQL documents identify schema v16, its Python demonstrator asserts schema v13, and the local database reports schema v17; these artifacts are not interchangeable and all adapter behavior must be version-gated.
- S04 identified `/Applications/OSCAR20.app` as version 2.0.0 and the active database at the sanitized path `$HOME/Documents/OSCAR20_Data/oscar.db`; a protected disposable copy reported schema version 17.
- `docs/research/oscar-local-database-inventory.md` documents the sanitized inventory, closed-state copy procedure, verification evidence, and cleanup.
- `docs/research/oscar-official-demo-result.md` records the exact environment, sanitized command, repeatable failure, and cleanup for the unmodified official Python demonstrator.
- The official demo exits 1 at its first schema query with `sqlite3.OperationalError: attempt to write a readonly database` against the protected copy; it never reaches schema mismatch, profile lookup, or therapy rows.
- `docs/research/oscar-identity-session-schema-map.md` maps the minimum schema-17 fields for schema identity, profile selection, machine provenance, sessions, OSCAR-day context, and device-time corrections, with units and caveats.
- `docs/research/oscar-aircurve-asv-settings-events-map.md` maps the six fixed-EPAP ASV setting channels and six normalized respiratory-event kinds needed by the first PS Min experiment, including units, encodings, join rules, and missing-data behavior.
- `docs/research/oscar-aircurve-asv-signal-map.md` maps the three minimum signal inputs for independent analysis: 25 Hz Flow Rate, synchronized 25 Hz high-resolution Mask Pressure, and sparse Leak Rate, including binary decoding, timing, units, gaps, and quality behavior.
- The published schema documents stop at v16; the protected local schema-v17 copy adds `device_time_corrections`, while the earlier proposed `machine_time_offsets` table is absent.
- Schema-17 respiratory-event identity must come from the profile-scoped channel registry: the observed `respiratory_events.event_type` values contradict the schema-16 published enum, and `sessions.events_loaded` is not a reliable completeness gate in the scoped database.
- OSCAR/device-derived summary channels and event labels are reference inputs, not PAP Pilot's analytical result; companion metrics must be calculated independently from the mapped signals and retain their own provenance.
- Every completed sprint must end with its validated in-scope changes committed and a clean working tree.

## Last completed sprint

S10 — Implement guarded read-only connection.

## Validation performed

- Ran `PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover --start-directory tests --verbose`; all six tests passed without resource warnings.
- A supported synthetic schema-17 database returned its sentinel row through the guarded connection and held an explicit read transaction.
- `query_only` rejected a temporary-table write; after the test deliberately disabled `query_only`, SQLite `mode=ro` still rejected a main-database insert.
- The supported test database remained byte-for-byte unchanged, retained exactly one sentinel row, and produced no journal, WAL, or SHM sidecar.
- A nonexistent database was not created, absent/empty schema metadata raised `MissingSchemaVersionError`, and schema versions 16 and 18 raised `UnsupportedSchemaVersionError` before a connection was exposed; every rejection fixture remained byte-for-byte unchanged.
- Tests created only synthetic SQLite files in system temporary directories. No live or copied OSCAR database and no therapy row was accessed.
- `git diff --check` passed.

## Decisions and assumptions

- Only one Codex goal/sprint should be active at a time.
- Sprints deliberately stop at their stated completion check.
- Undiscovered work becomes a new queued sprint rather than silently expanding an active sprint.
- The user decided that working-name selection must precede version-control initialization and all technical development.
- The user decided that the plan will be maintained in place as `Plan.md`; Git history and focused decision records replace version-suffixed plan copies.
- The user decided to keep the product plan and execution queue separate: milestone gates stay in `Plan.md`, while all sprint identifiers, ordering, and status stay in `SPRINTS.md`.
- The user approved **PAP Pilot** as the working display name, written as two words and pronounced “P-A-P Pilot.”
- The approved identifiers are `pap-pilot`, `pap_pilot`, and `pap_pilot.sqlite3`.
- “Pilot” is a mascot and guidance metaphor only; it does not imply autonomous device control or relax any safety boundary.
- Final branding, external name clearance, trademark review, domains, and app-store availability remain deferred.
- A sprint is not complete until its completion check passes, its in-scope changes are committed, and the working tree is clean.
- Metric-implementation sprints S22–S24 are placeholders until S21 selects the actual initial metric set.
- Private OSCAR/PAP data and local application databases must remain outside version control; later retained fixtures must follow their sprint's explicit de-identification and validation requirements.
- The exact SQL Notes artifact inspected is the OSCAR 2.0.1 `Notes.zip` identified by its recorded SHA-256; the stable release label and the internal schema-document versions are recorded separately rather than conflated.
- The Python demo has no internal semantic release number. Treat it as a member of the 2.0.1 Notes distribution that explicitly supports schema v13, not as proof of compatibility with schema v16.
- The upstream archive is not vendored; the repository retains its exact provenance and verification hashes only.
- A filesystem copy is made only after OSCAR closes and only with all existing `oscar.db` SQLite sidecars copied as one closed-state set.
- SQLite `immutable=1` may be used only on a trusted, fixed disposable copy, never on OSCAR's live database. It was required here after plain read-only access returned SQLite error 14 on the closed copy with no remaining WAL/SHM sidecars.
- Each demonstration run uses a fresh disposable copy; the S04 verification copy and S05 execution copy were both removed after their scoped checks.
- A failed official demo is a valid S05 result when its exact artifact, environment, command, exit status, error, and cleanup are reproducibly documented.
- S05 does not weaken copy protection or modify the official demo to bypass its read-only failure. S10 owns implementation and tests for the guarded connection behavior.
- For schema v17, profile ownership of sessions and time corrections is derived through `machines`; neither scoped child table contains `profile_id`.
- `schema_version` is treated as a current-state marker selected with `MAX(version)`, not as a required contiguous migration ledger; the observed database contains one row with value 17.
- Database row IDs, OSCAR's machine/session IDs, application version, schema version, and loader data version are distinct identities and must remain distinct in the adapter.
- Raw session boundaries are Unix epoch milliseconds. Raw and display-corrected times must remain separate, and OSCAR-day derivation requires the profile timezone/day-split context plus later cross-checking against OSCAR.
- The v17 correction mapping is version-specific and documentation-derived because the local correction table is empty. Range endpoints, open-ended sentinels, drift encoding, and sign behavior require focused synthetic tests before corrected time becomes authoritative.
- Enabled and non-summary flags do not prove a session has valid boundaries; later extraction must reject or flag zero and negative durations.
- For the first PS Min experiment, the required fixed-EPAP ASV setting context is `PAPMode`, `RMS9_Mode`, `EPAP`, `PSMin`, `PSMax`, and `IPAPHi`; settings are never carried forward across sessions.
- Pressure settings normalize to cm H₂O and retain decimal precision. The absence of a database unit column requires the planned OSCAR reference-night cross-check before fixture expectations become authoritative.
- Schema-17 respiratory-event identity is derived only from `(profile_id, channel_id) → channels.channel_code`; the raw `respiratory_events.event_type` is retained as opaque provenance and never decoded with the schema-16 enum.
- The first experiment's event allowlist is OA, CA, UA, H, RERA, and Large Leak. `AllApnea` is excluded to prevent aggregate/component double-counting, and CSR, periodic breathing, user flags, and signal data remain out of scope.
- Event-row absence remains unknown rather than zero because the observed `events_loaded` flag is inconsistent with row presence. S12 must preserve incompleteness and S14 must establish zero-count behavior against OSCAR.
- Non-contained Large Leak spans remain raw and flagged; no clipping, counting, or session reassignment is allowed before the OSCAR cross-check establishes intended behavior.
- The user reaffirmed that PAP Pilot must provide additional deterministic analysis rather than merely reproduce OSCAR outputs. Machine/OSCAR events and derived channels are comparison/reference inputs, not authoritative companion metrics.
- The minimum S08 input set is `FlowRate`, `MaskPressureHi`, and `Leak`. OSCAR/device-derived AHI, flow limitation, respiratory rate, tidal volume, minute ventilation, target ventilation, Ti, and Te are excluded from the required set and cannot silently substitute for PAP Pilot calculations.
- `MaskPressureHi` is the required pressure input because it is a 25 Hz waveform synchronized with flow. Sparse `Pressure`, low-resolution `MaskPressure`, and `EPAP` traces are not silent fallbacks.
- Flow and mask-pressure waveform timestamps derive from `first_time + i*rate`; their observed schema-17 `last_time` is end-exclusive. Leak timestamps derive only from the stored unsigned millisecond-delta array.
- EventLists remain separate segments. Missing signals and inter-list gaps are explicit quality state; the adapter never interpolates across them, carries a sparse value across a gap, or substitutes `session_channels` summaries for samples.
- `compressed_size` cannot determine whether a row is compressed in schema 17. Decode selection uses `compression_method` plus the mutually exclusive raw/compressed BLOBs, followed by length and checksum validation.
- Flow sign convention and whether the scoped ResMed `Leak` trace is excess versus total leak remain unproven by the inspected database contract; S14 must cross-check them against OSCAR before breath-phase or leak-threshold results become authoritative.
- The initial Python scaffold uses a `src` layout, setuptools as its build backend, Python 3.11 or newer, and no runtime dependencies.
- The `pap_pilot.adapter` namespace owns external data access, while `pap_pilot.engine` owns deterministic companion analysis; OSCAR-derived results must not cross that boundary as if they were PAP Pilot calculations.
- The smoke test uses Python's standard-library `unittest` so the scaffold does not introduce a test-framework dependency before one is needed.
- Guarded OSCAR access uses two independent controls: SQLite URI `mode=ro` protects the main database, while `PRAGMA query_only=ON` also prevents writes to temporary tables during normal adapter use.
- The wrapper begins a read transaction before selecting `MAX(schema_version.version)`, accepts only integer version 17, and closes the connection on success or failure.
- The wrapper does not silently add `immutable=1`; that flag remains restricted to a trusted, fixed disposable copy and must never be used against the live OSCAR database.

## Blockers

- No blocker prevents starting S11.
- The local database is schema v17 while the published data dictionary stops at v16. Later sprints must keep version-gating observed behavior and must not assume version equivalence.
- The contradictory respiratory-event enum, unreliable `events_loaded` flag, and non-contained Large Leak spans require explicit S12 extraction behavior and S14 OSCAR cross-checks.
- Signal gaps/missing lists, the `compressed_size` discrepancy, unresolved Flow Rate sign convention, and unresolved Leak subtype require explicit S13/S14 and later quality-rule handling; they do not block project scaffolding.
- The empty local correction table and invalid raw session boundaries remain explicit inputs to later guarded-connection, session-extraction, and structural-quality work.

## Resume instruction

```text
Read AGENTS.md, Plan.md, SPRINTS.md, and STATUS.md. Complete only S11.
Using the guarded connection and only a fresh disposable OSCAR database copy,
extract machine/profile provenance, session boundaries, and the six mapped ASV
settings for one selected night. Do not add events, waveforms, metrics, or
multiple-night queries. Update SPRINTS.md and STATUS.md, commit the completed
sprint, verify the working tree is clean, then stop without starting S12.
```
