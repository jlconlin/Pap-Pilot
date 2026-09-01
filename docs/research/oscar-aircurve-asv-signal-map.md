# OSCAR AirCurve 10 ASV signal map

**Mapped:** August 30, 2026 (America/Denver)

**Scope:** The minimum OSCAR schema-17 signal inputs needed to support PAP Pilot's independent analysis and evidence views for the retrospective PS Min experiment. This sprint maps storage and quality behavior only; it does not implement extraction, define metrics, or adopt OSCAR's derived outputs as PAP Pilot results.

## Analysis boundary

OSCAR remains the importer and canonical normalized data store. PAP Pilot is not an OSCAR report generator: its deterministic engine must calculate its own breath-level features, comparisons, and experiment evidence from the selected signals.

Machine-labeled events mapped in S07 remain useful overlays and comparison inputs. They are not ground truth and do not replace waveform analysis. Likewise, OSCAR/device-derived AHI, flow limitation, respiratory rate, tidal volume, minute ventilation, target ventilation, Ti, and Te are not selected as required S08 inputs. A later metric decision may use them as validation or secondary context, but it must not silently substitute them for a companion calculation.

The minimum selected set is therefore:

| Internal signal | OSCAR channel code | Why it is required | Source class |
|---|---|---|---|
| `flow_rate` | `FlowRate` | Primary input for PAP Pilot's own breath segmentation, morphology, variability/stability analysis, and representative breathing evidence. Exact derived metrics remain for S21. | Machine-recorded, OSCAR-normalized waveform |
| `mask_pressure` | `MaskPressureHi` | High-resolution pressure waveform synchronized with flow, allowing PAP Pilot to examine breath-by-breath pressure/pressure-support response rather than rely on a summary or sparse therapy-pressure trace. | Machine-recorded, OSCAR-normalized waveform |
| `leak_rate` | `Leak` | Time-resolved quality/confounder input so PAP Pilot can assess whether waveform evidence is contaminated instead of relying only on the machine's Large Leak flags. | Machine-recorded, OSCAR-normalized timed updates |

`Pressure`, `MaskPressure`, and `EPAP` event traces are not required while the synchronized high-resolution `MaskPressureHi` waveform is available. `AHI`, `FLG`, `RespRate`, `TidalVolume`, `MinuteVent`, `TgMV`, `Ti`, `Te`, `Snore`, and unrelated signals are excluded from the minimum set. This does not decide the S21 metric formulas; it establishes the smallest raw inputs capable of supporting independent analysis and the initial evidence view.

## Evidence boundary

The database evidence came only from a fresh protected disposable copy made with OSCAR closed, following `oscar-local-database-inventory.md`. SQLite opened that copy with `mode=ro&immutable=1`; the live database was never queried.

Documentation came from the official OSCAR 2.0.1 Notes archive already identified in `oscar-2-source-materials.md`:

| Item | Verified identity or purpose |
|---|---|
| OSCAR Notes archive | `https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip` |
| Archive SHA-256 | `b5ef2878d73175b62e29a9fce8373de0e697c234130528005c3d32e3d6399ef8` |
| Blob/timing reference | `Notes/Waveform Demo/python_waveform_demo_spec.md` and its matching Python script |
| Schema reference | `Notes/Database/DATABASE_SCHEMA.md` and `DATABASE_SCHEMA_REFERENCE.md` |
| ResMed channel context | `Notes/Wiki/OSCAR/S9 Data Format.mediawiki` and `OSCAR leaks.mediawiki` |
| Device pressure-unit reference | [ResMed AirCurve 10 CS PaceWave user guide](https://document.resmed.com/documents/products/machine/aircurve-series/user-guide/aircurve-10-cs-pacewave_user-guide_apac_eng.pdf) |

The published database documents describe schema 16 and the demonstrator asserts schema 13, while the protected local database reports schema 17. The local schema-17 DDL and scoped observations are authoritative for local field presence and behavior. Every adapter implementation must version-gate this mapping.

No profile name, serial number, therapy date, session identifier, decoded sample value, signal extrema, or signal-derived personal result is retained in this note.

## Source relationship

Samples are reached through this profile-scoped path:

```text
profiles.id
  └── machines.profile_id
        └── sessions.machine_id
              └── event_lists.session_id
                    └── event_data.eventlist_id

profiles.id + channels.channel_id
  └── event_lists.profile_id + event_lists.channel_id
```

Resolve each selected `channels.channel_code` for the session machine's profile, then join `event_lists` with both the session and resolved `channel_id`. Validate that `event_lists.profile_id` equals the machine's profile. Never hard-code channel integers or use an unscoped channel-code lookup.

One `(session_id, channel_id)` can have multiple EventLists, uniquely ordered by `eventlist_index`. `event_data` has exactly one row per EventList. The observed selected channels used zero-based contiguous indexes, but readers must validate rather than assume that invariant.

`session_channels` contains cached summaries, counts, and outer bounds. Its observed entries agree with the selected EventLists when present, so it may be used as a discovery/integrity cross-check. It cannot replace `event_lists` and `event_data` for waveform shape, exact timing, gaps, or independent analysis.

## Selected signal mapping

| Internal signal | Source location | Canonical unit | Sample timing | Value encoding | Quality caveats |
|---|---|---|---|---|---|
| `flow_rate` | Profile-scoped `channels.channel_code='FlowRate'` → `event_lists` → `event_data` primary array | L/min; observed raw dimension text is `L/M` | `event_type=0`; uniform 40 ms/sample (25 Hz) in the scoped AirCurve data | Little-endian signed `int16`; `physical = raw * gain + offset`. Observed gain is approximately 0.12 and offset 0, but both must be read per EventList. | Required for every independently analyzed interval. S14 established OSCAR's positive-inspiration/negative-expiration display convention for the reference night; later breath-phase classification still belongs to PAP Pilot. Do not fill gaps, smooth, resample, or baseline-correct in the adapter. |
| `mask_pressure` | Profile-scoped `channel_code='MaskPressureHi'` → `event_lists` → `event_data` primary array | cm H₂O; observed dimension text is `cmH2O` | `event_type=0`; uniform 40 ms/sample (25 Hz), with list bounds/counts exactly synchronized to `FlowRate` in the scoped copy | Little-endian signed `int16`; same gain/offset formula. Observed gain is approximately 0.02 and offset 0; never hard-code them. | A paired flow/pressure interval is required for breath-synchronized pressure-response analysis. Missing or misaligned pressure makes that analysis unavailable; sparse `Pressure` is not a silent fallback. S14C established the OSCAR Mask Pressure graph relationship for the reference night. |
| `leak_rate` | Profile-scoped `channel_code='Leak'` → `event_lists` → `event_data` primary and time arrays | L/min; `event_lists.dimension` is SQL `NULL` in the scoped copy (an empty string is treated equivalently absent), while OSCAR's schema and ResMed loader assign the channel L/min | `event_type=1`; irregular timed updates. `rate=0`; absolute sample time is `first_time + uint32_delta_ms` | Primary values are little-endian signed `int16` with the gain/offset formula. Time deltas are little-endian unsigned `uint32`. Observed gain is approximately 1.2 and offset 0; read both per list. | OSCAR's `Leak` channel is unintentional/excess leak, distinct from `LeakTotal`, which includes natural mask vent leakage. Missing leak means quality is unknown, never zero. Keep stored updates exact; a later view may connect updates as steps only within an EventList and must never hold across gaps. |

The observed `channels.type` is the same broad numeric class for all three signals and does not distinguish uniform waveforms from sparse steps. `event_lists.event_type` is the authoritative encoding discriminator here: `0=EVL_Waveform`, `1=EVL_Event`.

## Common primary-array encoding

For every selected EventList:

1. Read `count`, `gain`, `offset`, `data_size`, `has_second_field`, and the timing fields from `event_lists`.
2. Read the unique `event_data` row.
3. For `compression_method=0`, require `data_blob` and no `data_compressed`. For `compression_method=1`, require `data_compressed` and decode Qt `qCompress` format: a four-byte big-endian uncompressed-length prefix followed by a zlib stream.
4. Require exactly `count * 2` uncompressed primary bytes, decode them as little-endian signed 16-bit integers, and calculate physical values as `raw * gain + offset`.
5. Verify the stored primary-data checksum with Qt's ISO 3309/X-25 CRC-16. A mismatch is an integrity failure for authoritative analysis even though the teaching demo merely warns.
6. Reject an unknown compression method, missing/dual primary BLOBs, invalid count/rate/gain/offset, size mismatch, unsupported second field, or failed decompression. Do not return partial values as valid evidence.

For uniform waveforms, `data_size` is the `count * 2` primary-array size. For sparse `Leak`, schema 17 stores `data_size=count * 6`, covering both the `count * 2` primary values and `count * 4` explicit timestamps; its `compressed_size` likewise covers the two selected storage BLOBs together. Validate each array length independently as well as the combined metadata.

The selected channels had `has_second_field=0` and no secondary BLOBs in the scoped copy. All observed primary arrays were stored uncompressed and had matching sizes; the documented compressed form must still be supported.

The schema-16 documentation says `compressed_size` is null for uncompressed data. In the schema-17 copy it was populated and equal to `data_size` even when `compression_method=0`; for sparse Leak that equality includes both raw BLOBs. Therefore `compressed_size` is provenance/diagnostic metadata only, not a storage-mode selector.

## Timing rules

### Uniform waveforms

For `FlowRate` and `MaskPressureHi`:

```text
sample_time_ms[i] = first_time + i * rate
i = 0 .. count-1
```

`rate` is milliseconds per sample, not hertz or seconds. The scoped values were exactly 40.0 ms/sample. Preserve the source `REAL`; the schema does not guarantee that every loader or future version uses an integral interval.

For every observed selected waveform list:

```text
last_time = first_time + count * rate
last_sample_time = first_time + (count - 1) * rate
```

Thus schema-17 `last_time` behaves as the end-exclusive boundary for these waveforms, despite the schema document calling it the last timestamp. Generate sample times from `first_time`, `count`, and `rate`; do not append a sample at `last_time`.

### Sparse leak steps

For `Leak`, load exactly `count * 4` bytes from whichever one of `time_blob` or `time_compressed` is populated, using qCompress decoding when required:

```text
sample_time_ms[i] = first_time + uint32_le_delta[i]
```

The observed deltas were zero-based, nondecreasing, within the EventList bounds, and the final delta landed on `last_time`. Values are irregular timed updates. OSCAR's graph connects them with straight segments or horizontal-then-vertical steps according to the square-wave display preference. The adapter must not invent a uniform sample interval from `rate`, extend the final value past the list boundary, or hold across a gap.

All timestamps remain raw Unix epoch milliseconds. Apply any supported session device-time correction consistently to a derived display timeline, while preserving the raw values and never writing corrected times to OSCAR.

## Segments, gaps, and missing data

Multiple EventLists are independent contiguous segments, commonly separated by mask-off or recording gaps. Process them in `eventlist_index` order, but do not concatenate them into a falsely continuous series. The scoped copy contained split lists and positive gaps for every selected signal.

`summary_only=0`, a positive session duration, and a cached `session_channels` row do not prove that every selected signal is usable. The scoped copy contained valid non-summary sessions missing one or more selected EventLists. Availability must be tracked independently:

- missing `FlowRate` means no breath-level independent analysis for that interval;
- missing or unsynchronized `MaskPressureHi` means no paired pressure-response analysis;
- missing `Leak` means leak-related quality is unknown; and
- a gap in any signal remains a gap and constrains every metric that needs that signal.

The observed flow and high-resolution mask-pressure lists were exactly paired by session, EventList index, bounds, count, and rate whenever present. This is a required validation for synchronized use, not a guarantee for another schema, loader, or damaged session.

Large leak can distort or suppress usable flow and event detection. Signal quality work must combine the leak trace, S07 Large Leak spans, sample/gap integrity, and later artifact rules. It must not treat apparently quiet flow or an absence of machine events during leak as evidence of stable breathing.

## Protected-copy validation

Sanitized validation established that:

- the three selected channel definitions exist and are enabled for the scoped profile;
- all selected EventLists and data rows have consistent profile/session/channel joins and Unix-millisecond bounds within their associated valid sessions;
- flow and high-resolution mask pressure are uniform 25 Hz waveforms and are exactly synchronized whenever present;
- leak is a sparse timed-update trace with a complete little-endian millisecond-delta array;
- primary and time-array lengths match their counts, selected lists have no second field, and EventList indexes are zero-based and contiguous;
- all observed selected BLOBs use the uncompressed storage branch, while `compressed_size` remains populated and therefore cannot select the branch;
- stored checksums are present, and a shortest-list sample from each selected channel matched the official CRC implementation; and
- signal absence and inter-list gaps occur in otherwise enabled, positive-duration, non-summary sessions and must remain explicit.

Exact sample values, extrema, session counts, dates, and identifiers were not retained.

## Implementation boundary

This mapping and the S14/S14C reference-night cross-check supply the three required signal identities, locations, units, timing, binary encodings, display relationships, and quality caveats. Later work must still:

- define quality rules in S18/S20 rather than hiding missing or corrupted data in the adapter;
- choose exact companion-derived metrics and formulas only in S21; and
- keep every derived result labeled companion-derived, with source intervals, algorithm version, units, exclusions, and limitations.
