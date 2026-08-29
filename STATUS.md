# PAP Pilot — session handoff

**Updated:** August 28, 2026  
**Governing plan:** `Plan.md`
**Current sprint:** None — S03 completed; stopped before S04
**Next sprint:** S04 — Inventory the local OSCAR database

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
- Every completed sprint must end with its validated in-scope changes committed and a clean working tree.

## Last completed sprint

S03 — Record OSCAR source-material provenance.

## Validation performed

- Verified the official OSCAR download page identifies release 2.0.1, dated June 23, 2026, and links `https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip` as **OSCAR 2.0 SQL Notes**.
- Verified the archive returned HTTP 200 with `Last-Modified: Tue, 23 Jun 2026 16:42:55 GMT` and a content length of 847,895 bytes.
- `unzip -t` passed for all 188 archive entries.
- Verified the archive SHA-256 is `b5ef2878d73175b62e29a9fce8373de0e697c234130528005c3d32e3d6399ef8`.
- Located `Notes/Waveform Demo/oscar_waveform_demo.py` and `python_waveform_demo_spec.md`; verified their hashes and confirmed the copies under `Notes/Accessing OSCAR Data/` are byte-identical.
- Confirmed the SQL schema documents identify schema v16 and the demonstrator/specification target schema v13; the specification is marked `Draft` and dated April 14, 2026.
- No OSCAR database was located or opened, no schema was reverse engineered, no bundled code was run, and no external artifact or health data was added to the repository.
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

## Blockers

- No blocker is established for starting S04.
- S04 must locate the active local database, record OSCAR/schema versions without exposing therapy data, and verify a protected disposable-copy procedure.
- Before S05 runs the official demonstrator, its schema-v13 assertion must be checked against the schema version established in S04; the bundled SQL documentation currently identifies schema v16.

## Resume instruction

```text
Read AGENTS.md, Plan.md, SPRINTS.md, and STATUS.md. Complete only S04.
Locate the active OSCAR database, record OSCAR and schema versions without
exposing therapy rows, and document and verify a protected disposable-copy
procedure. Do not run the Python demonstration against the live database.
Update SPRINTS.md and STATUS.md, commit the completed sprint, verify the working
tree is clean, then stop without starting S05.
```
