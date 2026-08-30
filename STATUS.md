# PAP Pilot — session handoff

**Updated:** August 30, 2026
**Governing plan:** `Plan.md`
**Current sprint:** None — S06 completed; stopped before S07
**Next sprint:** S07 — Map settings and events

## Current state

- The repository contains planning, decision, and exploratory branding documents; application implementation has not begun.
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
- The official 2.0.1 Notes bundle's SQL documents identify schema v16, while its Python demonstrator asserts schema v13; compatibility must be confirmed before the later demonstration sprint.
- S04 identified `/Applications/OSCAR20.app` as version 2.0.0 and the active database at the sanitized path `$HOME/Documents/OSCAR20_Data/oscar.db`; a protected disposable copy reported schema version 17.
- `docs/research/oscar-local-database-inventory.md` documents the sanitized inventory, closed-state copy procedure, verification evidence, and cleanup.
- `docs/research/oscar-official-demo-result.md` records the exact environment, sanitized command, repeatable failure, and cleanup for the unmodified official Python demonstrator.
- The official demo exits 1 at its first schema query with `sqlite3.OperationalError: attempt to write a readonly database` against the protected copy; it never reaches schema mismatch, profile lookup, or therapy rows.
- `docs/research/oscar-identity-session-schema-map.md` maps the minimum schema-17 fields for schema identity, profile selection, machine provenance, sessions, OSCAR-day context, and device-time corrections, with units and caveats.
- The published schema documents stop at v16; the protected local schema-v17 copy adds `device_time_corrections`, while the earlier proposed `machine_time_offsets` table is absent.
- Every completed sprint must end with its validated in-scope changes committed and a clean working tree.

## Last completed sprint

S06 — Map identity and session tables.

## Validation performed

- Re-downloaded the official OSCAR 2.0.1 Notes archive and verified its SHA-256 against the S03 provenance record.
- Confirmed OSCAR was closed and source WAL/SHM files were absent before making a fresh database copy outside the repository.
- Byte- and hash-verified the copy against the source, then protected it as file mode `0400` inside a mode-`0500` directory.
- Inspected only scoped schema metadata and sanitized profile/machine/session/time-correction invariants through SQLite 3.51.0 using `mode=ro&immutable=1`.
- Confirmed the local schema-v17 DDL for `schema_version`, `profiles`, `machines`, `sessions`, `user_info`, `profile_preferences`, and `device_time_corrections` and the required join relationships.
- Confirmed profile/machine/session foreign-key relationships have no observed orphans, scoped identifiers satisfy their documented compound uniqueness, session times have Unix-millisecond magnitude, and flags use 0/1.
- Confirmed every observed session duration equals `end_time - start_time`, while also finding enabled, non-summary rows with zero or negative duration; exact identifiers and therapy dates were not retained.
- Confirmed the active profile's two stored timezone sources agree, the scoped OSCAR-day preferences are present with expected type hints, legacy `ClockDrift` is zero or absent, and `device_time_corrections` currently has no rows.
- Reconfirmed OSCAR remained closed, live sidecars remained absent, source and copy remained byte-identical, and no copy sidecar was created.
- Removed the archive, extracted notes, and disposable database; confirmed the exact temporary workspace is absent and no OSCAR data entered the repository.
- Mechanically checked all 47 mapping rows have a nonempty internal value, source, type/unit, and caveat; excluded settings/event/signal tables are not mapped.
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

## Blockers

- No blocker prevents starting S07.
- The local database is schema v17 while the published data dictionary stops at v16. S07 must continue to compare official documentation with only the scoped observed DDL and must not assume version equivalence.
- The empty local correction table and invalid raw session boundaries do not block S07, but they remain explicit inputs to later guarded-connection, session-extraction, and structural-quality work.

## Resume instruction

```text
Read AGENTS.md, Plan.md, SPRINTS.md, and STATUS.md. Complete only S07.
Using only official documentation and a protected disposable copy with OSCAR
closed, map only the AirCurve 10 ASV settings and event fields needed by the
first experiment. Do not map signals/waveforms, unused device modes, identity
fields already completed in S06, or unrelated tables.
Update SPRINTS.md and STATUS.md, commit the completed sprint, verify the working
tree is clean, then stop without starting S08.
```
