# Local OSCAR database inventory

**Recorded:** August 29, 2026 (America/Denver)

**Scope:** Application/database identification and disposable-copy safety only.
No therapy row has been queried, and the official demonstration has not been
run.

## Installed application

| Field | Observed value |
|---|---|
| Application | `/Applications/OSCAR20.app` |
| Bundle identifier | `org.oscar-team.OSCAR20` |
| Bundle version | `2.0.0` |
| Version source | `CFBundleShortVersionString` in `Contents/Info.plist` |

The installed version is 2.0.0, not the 2.0.1 release associated with the
source-material bundle recorded in `oscar-2-source-materials.md`. No upgrade
was attempted in S04.

## Active database

Paths are written with `$HOME` to avoid retaining the local account name.

| Field | Sanitized path |
|---|---|
| OSCAR data directory | `$HOME/Documents/OSCAR20_Data` |
| Database | `$HOME/Documents/OSCAR20_Data/oscar.db` |
| SQLite sidecars observed while OSCAR was open | `oscar.db-wal`, `oscar.db-shm` |
| Schema version | 17 |

The database was identified both as the only matching database in the OSCAR
2 data directory and as an open file of the running OSCAR20 process. The same
process also held the WAL and shared-memory sidecars open. That state was used
only to confirm which database is active; no database content was read.

## Safe disposable-copy procedure

1. Quit OSCAR normally. Do not continue merely because its windows are hidden.
2. Verify that this command produces no process:

   ```bash
   pgrep -ifl '/Applications/OSCAR20\.app/Contents/MacOS/OSCAR20'
   ```

3. Create a destination outside the repository with mode `0700`:

   ```bash
   oscar_source_dir="$HOME/Documents/OSCAR20_Data"
   oscar_copy_dir="$(mktemp -d /tmp/pap-pilot-oscar.XXXXXX)"
   chmod 700 "$oscar_copy_dir"
   ```

4. With OSCAR still closed, copy the database and every existing SQLite
   sidecar as one closed-state set. Copy only the known filenames:

   ```bash
   cp -p "$oscar_source_dir/oscar.db" "$oscar_copy_dir/oscar.db"
   for oscar_suffix in -wal -shm; do
       if test -e "$oscar_source_dir/oscar.db$oscar_suffix"; then
           cp -p "$oscar_source_dir/oscar.db$oscar_suffix" \
               "$oscar_copy_dir/oscar.db$oscar_suffix"
       fi
   done
   ```

5. Before any SQLite access, verify that each source/copy pair has the same
   byte count and SHA-256 digest.
6. Protect the completed copy and its directory:

   ```bash
   chmod 400 "$oscar_copy_dir"/oscar.db*
   chmod 500 "$oscar_copy_dir"
   ```

7. Verify that neither the directory nor copied files are writable.
8. Query only `MAX(version)` from `schema_version`, and only through a SQLite
   `mode=ro&immutable=1` URI pointed at the protected disposable copy. The
   `immutable` flag is appropriate only because this is a trusted, fixed copy;
   never use it on the live OSCAR database. Do not enumerate tables or query
   profile, machine, session, setting, event, or waveform rows in S04.
9. Keep the copy outside the repository. Remove it after verification; S05
   should make a fresh copy using the same procedure.

## Verification

- Confirmed the OSCAR20 process was absent before copying and remained absent
  through the final source check.
- After normal shutdown, neither `oscar.db-wal` nor `oscar.db-shm` remained at
  the source. Only `oscar.db` therefore belonged to the closed-state copy set.
- Created a unique `/tmp` directory with mode `0700` and copied only
  `oscar.db`. Source and copy byte counts and SHA-256 digests matched before
  database access. The digest and database size are intentionally not retained
  here because they are unnecessary local-health-data identifiers.
- SQLite 3.51.0 plain `mode=ro` access returned error 14 after normal shutdown
  left the formerly WAL-backed database without sidecars. Read-only access
  with `mode=ro&immutable=1` succeeded against the trusted disposable copy.
- Queried only `MAX(version)` from `schema_version`; it returned schema version
  **17**. No therapy table or row was queried.
- Set the copied database to mode `0400` and its directory to `0500`. Both
  tested non-writable. The same immutable read-only schema query still
  succeeded, the copy digest remained unchanged, and no WAL, SHM, or journal
  sidecar was created.
- Rechecked the live source after verification: OSCAR remained closed, source
  sidecars remained absent, and the source digest matched its pre-copy value.
- Restored owner-write permission only on the disposable path so it could be
  deleted, then confirmed the temporary copy was absent. No OSCAR data was
  added to the repository.

The installed application (2.0.0), local database schema (17), published SQL
Notes (schema 16), and official Python demonstrator (schema 13) therefore do
not share one version. S05 must treat the official demo's schema check as an
expected compatibility boundary and record its result without modifying the
demo.
