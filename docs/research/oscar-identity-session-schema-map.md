# OSCAR identity and session schema map

**Mapped:** August 30, 2026 (America/Denver)

**Scope:** The minimum OSCAR fields required to identify the schema, select a profile, preserve machine provenance, identify sessions, interpret session-day boundaries, and retain device-time corrections. Settings, events, waveforms, summaries, and unrelated tables are intentionally excluded.

## Evidence boundary

The source artifact is the official OSCAR 2.0.1 `Notes.zip` already recorded in `oscar-2-source-materials.md`:

| Item | Verified identity |
|---|---|
| Archive URL | `https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip` |
| Archive SHA-256 | `b5ef2878d73175b62e29a9fce8373de0e697c234130528005c3d32e3d6399ef8` |
| Published schema documents | `Notes/Database/DATABASE_SCHEMA.md`, `DATABASE_SCHEMA_REFERENCE.md`, and `DATA_DICTIONARY.md` |
| Session-day reference | `Notes/Waveform Demo/python_waveform_demo_spec.md` and its matching Python demo |
| Time-correction references | `Notes/Developer Notes/Clock Drift Plan.md`, `TIME_ALIGNMENT_CODE_REVIEW.md`, `time differences labels.md`, and `Eliminate DST zone.md` |

The published schema documents stop at schema **16**. The installed OSCAR 2.0.0 database reports schema **17**. The bundled time-alignment review says the `device_time_corrections` migration is v17, and the protected local copy confirms that table's exact DDL. Therefore:

- the schema-v16 documents define the profile, machine, and session baseline;
- the schema-v17 disposable copy is authoritative for which scoped columns and constraints are actually present locally;
- the bundled developer notes supply the only official semantics found for the v17 correction fields; and
- every implementation must version-gate this mapping rather than treating it as a contract for another OSCAR schema.

No username, folder path, serial number, therapy date, session identifier, or correction reason is retained in this note.

## Relationship spine

Only this join path is required for the first adapter work:

```text
profiles.id
  └── machines.profile_id
        ├── sessions.machine_id
        └── device_time_corrections.machine_id
```

`sessions` and `device_time_corrections` do not contain `profile_id` in the observed schema. Profile ownership must be established through `machines`.

## Schema identification

| Internal value | OSCAR source | Type or unit | Required interpretation and caveat |
|---|---|---|---|
| `oscar_schema_version` | `MAX(schema_version.version)` | Integer schema revision | The official demo uses `MAX(version)`. The observed database contains one current-state row, version 17, rather than a contiguous migration ledger. Reject an absent, null, or unsupported value. |
| `schema_applied_at` | `schema_version.applied_at` for the selected version | SQLite timestamp text | Provenance only. `CURRENT_TIMESTAMP` is UTC, but the external documents do not promise a stable display format beyond text. |

`machines.data_version` is a loader-data version and is not interchangeable with `schema_version.version`, the OSCAR application version, or the Notes archive release.

## Profile and session-calendar mapping

| Internal value | OSCAR source | Type or unit | Required interpretation and caveat |
|---|---|---|---|
| `profile_db_id` | `profiles.id` | Unitless integer | Database primary key and join identity. It is not a person identifier and must not be assumed stable after export, restore, or migration. |
| `profile_name` | `profiles.username` | Case-sensitive text | Human selection label used by the official demo. It is sensitive and must not be logged in ordinary diagnostics. |
| `profile_status` | `profiles.status` | Enum text | Values are `active`, `missing`, or `archived`; normal selection requires `active`. A row's existence alone does not make it selectable. |
| `profile_timezone` | `user_info.timezone`, joined by `user_info.profile_id = profiles.id` | IANA timezone text | Nullable in the schema. The observed active profile also has a matching `profile_preferences` row at category `profile`, key `TimeZone`, type `string`; treat disagreement or absence as a validation failure rather than guessing. The bundled DST note says some OSCAR import logic uses the system timezone, so this field is not proof of how every raw timestamp was decoded. |
| `oscar_day_split_time` | `profile_preferences.value` where `profile_id=profiles.id`, category=`profile`, key=`DaySplitTime` | Local wall-clock time text; `data_type=time` | The official waveform demo hard-codes noon, while the bundled clock-drift plan refers to the configured profile split. Preserve the setting for later cross-checking; do not silently replace it with noon. |
| `lock_summary_sessions` | `profile_preferences.value` where `profile_id=profiles.id`, category=`profile`, key=`LockSummarySessions` | Boolean stored as text; `data_type=bool` | The clock-drift plan says summary-only sessions use noon when this is true. The generic preference table does not enforce boolean encoding in SQL. |

`profiles.data_folder` and personal columns in `user_info` are not needed for the mapping and must not enter the companion's normalized identity record.

## Machine mapping

| Internal value | OSCAR source | Type or unit | Required interpretation and caveat |
|---|---|---|---|
| `machine_db_id` | `machines.id` | Unitless integer | Database primary key used by `sessions.machine_id` and `device_time_corrections.machine_id`. |
| `profile_db_id` | `machines.profile_id` | Unitless integer | Foreign key to `profiles.id`. |
| `machine_source_id` | `machines.machine_id` | Unitless integer | OSCAR's machine ID, unique only together with `profile_id`. It is distinct from `machines.id`. |
| `loader_name` | `machines.loader_name` | Text | Loader provenance. Do not infer therapy mode from this value. |
| `machine_type_code` | `machines.machine_type` | Integer enum | The dictionary gives only partial examples. It is a broad OSCAR machine class, not an AirCurve ASV mode or therapy-setting value. Preserve the code without inventing unsupported labels. |
| `brand` | `machines.brand` | Text | Nullable display provenance. |
| `model` | `machines.model` | Text | Nullable display provenance. |
| `series` | `machines.series` | Text | Nullable display provenance. |
| `model_number` | `machines.model_number` | Text | Nullable device provenance. |
| `serial_number` | `machines.serial_number` | Text | Nullable stable device label, but sensitive. It may be used locally for provenance and matching; never include its raw value in fixtures, logs, or research notes. |
| `loader_data_version` | `machines.data_version` | Unitless integer revision | Loader-specific data-format version, not the database schema version. The observed DDL permits its default value of zero. |
| `last_imported_at` | `machines.last_imported` | ISO-8601 text | Nullable import provenance, not a therapy-session boundary. Timezone precision must be preserved as stored. |
| `purge_cutoff_date` | `machines.purge_date` | ISO-8601 date text | Nullable. A value means historical absence may be deliberate; it is not evidence that no earlier therapy occurred. |

`machines.properties`, row-creation metadata, and any device setting are outside this sprint's required identity record.

## Session mapping

| Internal value | OSCAR source | Type or unit | Required interpretation and caveat |
|---|---|---|---|
| `session_db_id` | `sessions.id` | Unitless integer | Database primary key used by child tables. |
| `session_source_id` | `sessions.session_id` | Unitless integer | OSCAR session ID, unique only together with `machine_id`. Do not confuse it with `sessions.id`. |
| `machine_db_id` | `sessions.machine_id` | Unitless integer | Foreign key to `machines.id`; this join supplies profile and device provenance. |
| `raw_start_ms` | `sessions.start_time` | Unix epoch milliseconds | The official waveform specification explicitly says milliseconds, not seconds. Preserve the raw integer. |
| `raw_end_ms` | `sessions.end_time` | Unix epoch milliseconds | Preserve independently of duration and any display correction. |
| `raw_duration_ms` | `sessions.duration` | Milliseconds | The observed rows satisfy `duration = end_time - start_time`, but enabled, non-summary rows with zero and negative values exist. Validate `end > start` and `duration > 0`; flags alone do not establish a usable session. |
| `enabled` | `sessions.enabled` | Boolean integer, 0/1 | The official demo selects `1`. Disabled rows remain part of OSCAR history and must not be silently treated as active therapy. |
| `summary_only` | `sessions.summary_only` | Boolean integer, 0/1 | A summary-only session has no waveform according to the official demo. This flag does not validate its time bounds. |
| `no_settings` | `sessions.no_settings` | Boolean integer, 0/1 | Session completeness signal only. The settings themselves are deliberately not mapped in S06. |
| `events_loaded` | `sessions.events_loaded` | Boolean integer, 0/1 | Session completeness signal only. Event rows and meanings are deliberately not mapped in S06. |
| `oscar_day` | Derived from `raw_start_ms`, the profile's local-time context, `DaySplitTime`, and `LockSummarySessions` | Local calendar date, `YYYY-MM-DD` | The schema has no direct OSCAR-day column on `sessions`. The schema-v13 demo uses `[D 12:00, D+1 12:00)` via SQLite `localtime`; the newer time-alignment notes describe the configured split and special noon behavior for locked summary sessions. This derivation must be cross-checked against OSCAR before it becomes authoritative. |
| `profile_db_id` | Derived through `sessions.machine_id → machines.id → machines.profile_id` | Unitless integer | Never infer profile ownership from globally comparing `session_id`. |

`sessions.created_at` and `updated_at` are database-row metadata, not device or therapy times, and are not needed in the first normalized session identity.

## Device-time-correction mapping

Schema 17 contains `device_time_corrections`; the earlier `machine_time_offsets` table proposed in the bundled clock-drift plan is absent. The observed correction table has no rows, so its row-level behavior is mapped from the exact DDL plus the bundled v17 time-alignment review, not inferred from local correction values.

| Internal value | OSCAR source | Type or unit | Required interpretation and caveat |
|---|---|---|---|
| `correction_id` | `device_time_corrections.id` | Unitless integer | Database row identity. Together with `undone_at`, it supports historical correction rows; the DDL alone does not prohibit every in-place update. |
| `machine_db_id` | `device_time_corrections.machine_id` | Unitless integer | Foreign key to `machines.id`; profile ownership is derived through that machine. |
| `date_from` | `device_time_corrections.date_from` | OSCAR-day date text, `YYYY-MM-DD` | Required start of the applicable day range. The official notes do not provide a stable external contract for endpoint filtering, so implementation tests must confirm boundary behavior. |
| `date_to` | `device_time_corrections.date_to` | OSCAR-day date text or null | Null is intended as open-ended for timezone rows, while the reviewed code used `2099-12-31` for other open-ended types. Support both representations and do not treat the sentinel as a real clinical cutoff. |
| `correction_type` | `device_time_corrections.type` | Enum text | SQL permits `timezone`, `travel`, `dst`, `reset`, `offset`, and `drift`. `travel`, `dst`, and `reset` are organizational labels with constant-offset math; `timezone` supersedes an earlier open-ended timezone row; only `offset` rows feed the documented drift fitting workflow. |
| `constant_offset_ms` | `device_time_corrections.offset_ms` | Signed milliseconds | Used by non-drift rows. The notes describe adding it to raw device time; positive therefore moves displayed/accessed time forward. Nullable in SQL, so validate it for applicable types. |
| `drift_intercept_ms` | `device_time_corrections.c0_ms` | Signed milliseconds | Drift-model intercept. Nullable in SQL and meaningful only for a drift row. |
| `drift_slope_encoding` | `device_time_corrections.c1` | Dimensionless, milliseconds per millisecond with an encoding offset | The reviewed v17 code stores `fitted_slope + 1.0` and recovers `fitted_slope` as `c1 - 1.0`. The review calls this fragile; preserve the raw value and version-gate its interpretation. |
| `reason` | `device_time_corrections.reason` | Text | Optional human provenance and potentially sensitive; do not emit it to ordinary logs. |
| `applied_at` | `device_time_corrections.applied_at` | SQLite UTC timestamp text | Audit metadata for row creation, not the effective therapy date. |
| `undone_at` | `device_time_corrections.undone_at` | Nullable timestamp text | Null denotes a currently active historical row. A non-null value preserves the superseded/undone record and excludes it from active correction math. |
| `active_correction_ms` | Derived from all date-matching rows with `undone_at IS NULL`, using `type`, `offset_ms`, `c0_ms`, and `c1` | Signed milliseconds | Contributions stack. The formula below is specific to the reviewed v17 implementation and requires synthetic verification before authoritative use. |
| `display_start_ms` | `sessions.start_time + active_correction_ms` | Unix epoch milliseconds | Display/access-time boundary only; retain `raw_start_ms` separately and do not persist this value back to OSCAR. |
| `display_end_ms` | `sessions.end_time + active_correction_ms` | Unix epoch milliseconds | Display/access-time boundary only; retain `raw_end_ms` separately and do not use this derivation to conceal an invalid raw session. |

For an active row whose date range matches the session's OSCAR day, the bundled review describes these version-specific contributions:

```text
non-drift contribution_ms = offset_ms
drift contribution_ms = -(c0_ms + (c1 - 1.0) * oscar_day_noon_epoch_ms)
total_correction_ms = sum(all matching active row contributions)
display_start_ms = raw_start_ms + total_correction_ms
display_end_ms = raw_end_ms + total_correction_ms
```

These are display/access-time values. The official notes say the raw session timestamps and cached raw channel bounds remain unmodified, and they identify a reviewed issue where day classification occurs before corrections are available. The companion must therefore retain raw and corrected values separately and must not rewrite the OSCAR-day assignment merely from this formula without an OSCAR cross-check.

## Protected-copy observations

The schema was inspected only through SQLite 3.51.0 using a `mode=ro&immutable=1` URI against a file-mode `0400` copy in a directory of mode `0500`. Before copying, OSCAR was closed and the live database had no WAL or SHM sidecar. Source and copy byte counts and SHA-256 digests matched; the private database size and digest are not retained.

Sanitized validation established that:

- `schema_version` contains the current value 17 as a single row;
- all scoped columns and constraints shown above exist in the protected copy;
- scoped profile-to-machine and machine-to-session relationships have no observed orphan rows;
- `(profile_id, machine_id)` and `(machine_id, session_id)` are unique as documented;
- observed session boundary values have Unix-millisecond magnitude, session flags use 0/1, and every observed `duration` equals `end_time - start_time`;
- some enabled, non-summary sessions nevertheless have zero or negative raw duration, requiring an explicit later validity check;
- the active profile's `user_info.timezone` and mirrored `TimeZone` preference agree, and the scoped split-time preferences are present with the expected type hints;
- the legacy `ClockDrift` preference is zero or absent; and
- `device_time_corrections` is present but currently empty.

No settings, event, waveform, summary, or unrelated data row was queried. After inspection, OSCAR was still closed, source sidecars were still absent, the source and copy remained byte-identical, and no sidecar had been created beside the copy. The official archive, extracted notes, and disposable database were then removed from the temporary workspace, and that workspace's absence was verified.

## Implementation boundary

This mapping supplies field names, units, relationships, and known caveats; it does not design or implement the adapter. Later work must still:

- make the schema-17 support decision explicit and reject other versions by default;
- validate positive session bounds rather than relying on OSCAR flags;
- cross-check OSCAR-day and corrected-time behavior against OSCAR;
- test the v17 correction formula and range endpoints with synthetic rows before treating corrected time as authoritative; and
- keep settings, events, and waveforms in their dedicated mapping sprints.
