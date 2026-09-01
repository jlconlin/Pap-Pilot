# OSCAR AirCurve 10 ASV settings and event map

**Mapped:** August 30, 2026 (America/Denver)

**Scope:** The minimum OSCAR schema-17 settings and normalized respiratory events needed to reconstruct the first retrospective PS Min experiment for the observed ResMed AirCurve 10 ASV. Signals, waveforms, summary metrics, comfort settings, and modes not used by that experiment are intentionally excluded.

## Evidence boundary

The database evidence came only from a fresh protected disposable copy made with OSCAR closed, using the procedure in `oscar-local-database-inventory.md`. The copy was opened with SQLite `mode=ro&immutable=1`; no live OSCAR database was queried.

The documentation evidence is:

| Item | Verified identity or purpose |
|---|---|
| OSCAR Notes archive | `https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip` |
| Archive SHA-256 | `b5ef2878d73175b62e29a9fce8373de0e697c234130528005c3d32e3d6399ef8` |
| Schema references | `Notes/Database/DATABASE_SCHEMA.md`, `DATABASE_SCHEMA_REFERENCE.md`, and `DATA_DICTIONARY.md` |
| Settings query reference | `Notes/Database/QUERY_RECENT_SESSION_SETTINGS.sql` |
| Device unit reference | [ResMed AirCurve 10 CS PaceWave user guide](https://document.resmed.com/documents/products/machine/aircurve-series/user-guide/aircurve-10-cs-pacewave_user-guide_apac_eng.pdf), technical specifications |

The published database documents describe schema 16, while the protected local database reports schema 17. The local schema-17 DDL is authoritative for the fields and constraints present locally. Published semantics are accepted only where they agree with scoped observations or are explicitly qualified.

No profile name, serial number, therapy date, session identifier, setting history, event count, or raw event timestamp is retained in this note. The known PS Min 2-to-1 experiment is already part of the governing product plan; no additional private setting values are recorded here.

## Required join rules

Settings and events share the same profile-scoped channel registry:

```text
profiles.id
  ├── channels.profile_id + channels.channel_id
  └── machines.profile_id
        └── sessions.machine_id
              ├── session_settings.session_id
              └── respiratory_events.session_id
```

For every child row, validate that its denormalized `profile_id` equals the session machine's `profile_id`. Resolve a channel with both that profile and the stored `channel_id`, then identify it by `channels.channel_code`. `channel_id` is an OSCAR channel constant, not a foreign key enforced by these tables. The adapter must not use a bare integer ID or an unscoped channel-code lookup.

The observed schema enforces one setting per `(session_id, channel_id)`. It does not enforce an equivalent uniqueness constraint for respiratory events.

## Therapy-setting mapping

The first experiment needs the changed PS Min value plus enough therapy context to prove that compared sessions use the same supported ASV mode and pressure envelope.

| Internal value | OSCAR source after channel resolution | Encoding or unit | Missing-data and validation behavior |
|---|---|---|---|
| `therapy_mode` | `session_settings.value` where `channel_code='PAPMode'` | Integral lookup code stored as `REAL`; relevant code `6` resolves through `channel_options` to `ASV (Fixed EPAP)` | Required. Reject a non-integral or unknown code. Do not carry a prior session's value forward. |
| `loader_mode` | `session_settings.value` where `channel_code='RMS9_Mode'` | Integral loader-specific lookup code stored as `REAL`; relevant code `7` resolves to `ASV` | Required as a cross-check for this ResMed loader. It must agree with `therapy_mode`; disagreement or absence makes the session unsupported for this experiment. |
| `epap_cm_h2o` | value where `channel_code='EPAP'` | Numeric `REAL`, cm H₂O | Required fixed expiratory pressure. Preserve decimal precision; do not assume an integer setting. |
| `ps_min_cm_h2o` | value where `channel_code='PSMin'` | Numeric `REAL`, cm H₂O | Required experiment variable. Missing means the session cannot establish its experiment arm. Never infer it from adjacent sessions. |
| `ps_max_cm_h2o` | value where `channel_code='PSMax'` | Numeric `REAL`, cm H₂O | Required pressure-support envelope context. Validate `PS Min ≤ PS Max`. |
| `max_ipap_cm_h2o` | value where `channel_code='IPAPHi'` | Numeric `REAL`, cm H₂O | Required maximum inspiratory-pressure context. Retain the source value; use `EPAP + PS Max = Max IPAP` only as a consistency check for this fixed-EPAP mode, not as a substitute for a missing row. |

`session_settings.value` is the authoritative scalar for these six channels. Their observed rows use the `numeric` data-type hint and have no `json_value`; `json_value` is for complex values and is not part of this mapping. There is no unit column on the setting row or channel registry. The cm H₂O normalization comes from the pressure-channel meanings and the official ResMed guide, which expresses device pressure in cm H₂O (and equivalently hPa) with 0.1 cm H₂O display resolution. A later OSCAR UI cross-check remains required before these units become reference-fixture expectations.

Only the two relevant mode codes above are mapped. CPAP, APAP, bilevel, ASVAuto, AVAPS, iVAPS, PAC, and other lookup values are outside S07; their presence in `channel_options` does not authorize the first experiment to use them.

`sessions.no_settings=1` is an explicit missing-settings signal, but the adapter must also verify every required channel row independently. A missing row remains missing even when `no_settings=0`. In the scoped protected copy, every enabled positive-duration AirCurve 10 ASV session had exactly one of each required row, the two mode fields consistently identified fixed-EPAP ASV, and the pressure-order/envelope checks passed.

## Required respiratory-event channels

The first experiment needs machine-labeled respiratory disturbances for later event-count evidence and Large Leak spans for later night-quality evaluation. It must not count the `AllApnea` aggregate channel because doing so alongside the component apnea channels would risk double-counting.

| Internal event kind | Required `channels.channel_code` | OSCAR label | Interpretation |
|---|---|---|---|
| `obstructive_apnea` | `Obstructive` | OA | Discrete machine-labeled obstructive apnea event. |
| `clear_airway_apnea` | `ClearAirway` | CA | Discrete machine-labeled clear-airway apnea event. This is not relabeled as a clinical central-apnea diagnosis. |
| `unclassified_apnea` | `Apnea` | UA | Machine-labeled apnea that OSCAR could not classify as obstructive or clear-airway. |
| `hypopnea` | `Hypopnea` | H | Discrete machine-labeled hypopnea event. |
| `rera` | `RERA` | RE | Machine-labeled respiratory-effort-related-arousal event. |
| `large_leak` | `LeakSpan` | LL | Machine-labeled Large Leak span used as a quality input, not as an apnea or hypopnea. |

The registry contained all six enabled channel definitions for the scoped profile. Only UA, H, and LL rows happened to be present in the protected copy; the absence of observed OA, CA, or RERA rows does not remove those channel kinds from the required mapping.

CSR, periodic breathing, snore, user flags, derived summary counts, and all binary `event_lists`/`event_data` content are outside this sprint. S08 owns signal selection, and S12 owns event extraction for a selected reference night.

## Respiratory-event row mapping

| Internal value | OSCAR source | Encoding or unit | Required interpretation and caveat |
|---|---|---|---|
| `source_event_id` | `respiratory_events.id` | Unitless integer | Database-row provenance only; do not assume stability after reimport. |
| `session_db_id` | `respiratory_events.session_id` | Unitless integer | Foreign key to `sessions.id`. The session supplies machine and raw-boundary context. |
| `profile_db_id` | `respiratory_events.profile_id` | Unitless integer | Denormalized profile key. It must equal the joined machine profile. |
| `source_channel_id` | `respiratory_events.channel_id` | Nullable integer channel constant | Required in practice for this mapping. A null or unresolved value is an unknown event kind and must not be guessed from `event_type`. |
| `event_kind` | Derived from profile-scoped `channels.channel_code` | One of the six allowlisted kinds above | This is the authoritative event identity for schema 17. Preserve an unknown resolved code for diagnostics but do not silently count it. |
| `source_event_type` | `respiratory_events.event_type` | Opaque integer | Retain for provenance and validation only. Do not translate it with the published enum. |
| `raw_start_ms` | `respiratory_events.start_time` | Unix epoch milliseconds | Preserve exactly and apply any session device-time correction consistently later; do not overwrite raw time. |
| `raw_end_ms` | `respiratory_events.end_time` | Unix epoch milliseconds | Must be at least `raw_start_ms`. Preserve even when it falls outside the associated session boundary. |
| `duration_s` | `respiratory_events.duration` | Integer seconds | Must be nonnegative and satisfy `raw_end_ms - raw_start_ms = duration_s * 1000`. Do not reinterpret it as milliseconds. |

`desaturation`, `severity`, and `created_at` are not needed by the first experiment and are excluded. The first two were null on all scoped observed rows, and `created_at` is database metadata rather than a therapy timestamp.

## Schema-17 event-encoding conflict

The schema-16 documents label `respiratory_events.event_type` as `0=OA, 1=UA, 2=H, 3=RERA, 4=CAA, 5=User`. That mapping is contradicted by the schema-17 data:

- `event_type=1` occurs with both the `Hypopnea` and `Apnea` channels; and
- `event_type=0` occurs with `LeakSpan`.

The observed values instead behave like a structural category for the normalized rows (point events versus spans), but S07 does not assign a new enum without an authoritative schema-17 source. The safe rule is therefore to identify events through the profile-scoped channel registry and treat `event_type` as opaque. Any implementation that applies the published enum directly would misclassify this database.

## Missing data and boundary behavior

An empty set of event rows is not yet proof of zero events. In the scoped database, `sessions.events_loaded` remained `0` even for sessions that had normalized respiratory-event rows. Consequently that flag is not a reliable schema-17 completeness gate, and neither its value nor row absence may be converted automatically to a zero count. S12 must preserve an `unknown/incomplete` state, and S14 must cross-check the selected night's event counts against OSCAR before zero-event semantics become authoritative.

All observed scoped event rows had integer millisecond boundaries, nonnegative integer-second durations, resolvable profile-scoped channels, and the exact duration relationship above. Observed UA and H events were contained within their associated raw session bounds. Large Leak rows exposed a separate boundary caveat: some ended after the session, and some began exactly at the session end with no overlap. The adapter must retain the raw values and flag non-contained spans; it must not silently count, clip, or reassign them until the reference-night cross-check establishes OSCAR's intended behavior.

## Implementation boundary

This note defines source fields, encodings, units, allowlisted meanings, and missing-data behavior. It does not implement extraction or choose outcome weights. Later work must:

- schema-gate this mapping to the supported OSCAR version;
- resolve all channels through `(profile_id, channel_id)` and validate the denormalized profile;
- refuse to carry settings forward between sessions;
- keep raw event times separate from corrected display times;
- preserve unknown event completeness rather than manufacturing zero counts;
- cross-check settings, event counts, labels, and boundary behavior against OSCAR for the reference night; and
- keep waveform/signal parsing in its separate sprint.
