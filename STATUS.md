# PAP Pilot — session handoff

**Updated:** August 29, 2026
**Governing plan:** `Plan.md`
**Current sprint:** None — S04 completed; stopped before S05
**Next sprint:** S05 — Run the official demonstration

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
- Every completed sprint must end with its validated in-scope changes committed and a clean working tree.

## Last completed sprint

S04 — Inventory the local OSCAR database.

## Validation performed

- Read the installed OSCAR20 app bundle metadata and recorded version 2.0.0 without launching or changing the application.
- Located the sole `oscar.db` in the OSCAR 2 data directory and confirmed it was the active database from the files held open by OSCAR20; no database content was used for discovery.
- Refused to copy while OSCAR held the database, WAL, and SHM files open. Resumed only after a process check confirmed OSCAR was closed normally.
- Confirmed shutdown removed the source WAL and SHM files, then copied the closed `oscar.db` to a unique mode-`0700` directory outside the repository.
- Verified source/copy byte counts and SHA-256 digests matched. Exact size and digest were deliberately not retained in project documents.
- Queried only `MAX(version)` from `schema_version` on the disposable copy through SQLite read-only immutable mode; it returned schema version 17.
- Protected the copy as file mode `0400` and directory mode `0500`; both tested non-writable, the schema query remained readable, the digest stayed unchanged, and no SQLite sidecar was created.
- Confirmed OSCAR remained closed and the live source digest remained unchanged throughout verification.
- Removed the disposable copy after verification and confirmed no database or health-data artifact was added to the repository.
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
- S05 must create a fresh disposable copy rather than depend on S04's removed verification copy.

## Blockers

- No blocker prevents starting S05.
- The installed application is 2.0.0 and its database is schema v17, while the published SQL Notes identify schema v16 and the official demonstrator asserts schema v13. S05 must preserve the demo unchanged and record this expected compatibility result.

## Resume instruction

```text
Read AGENTS.md, Plan.md, SPRINTS.md, and STATUS.md. Complete only S05.
With OSCAR closed, make a fresh protected disposable database copy using the
S04 procedure. Run the unmodified official Python demonstration only against
that copy and capture a sanitized, reproducible result, including an expected
schema-version failure if that is what occurs.
Update SPRINTS.md and STATUS.md, commit the completed sprint, verify the working
tree is clean, then stop without starting S06.
```
