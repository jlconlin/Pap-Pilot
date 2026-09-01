# PAP Pilot — session handoff

**Updated:** September 1, 2026
**Governing plan:** `Plan.md`
**Current sprint:** None — S14C completed; Milestone 1 accepted
**Next sprint:** S15 — Define normalized core records

## Current state

- The Python application scaffold now uses a `src` layout with importable `pap_pilot`, `pap_pilot.adapter`, and `pap_pilot.engine` packages.
- `pyproject.toml` defines an installable, dependency-free Python package, and `README.md` documents the isolated editable-install and smoke-test commands.
- The adapter and deterministic engine are separate package namespaces; one-session summary, machine/OSCAR event, Flow Rate, Mask Pressure, and Leak extraction are implemented, while metrics, web UI, and AI implementation have not begun.
- `pap_pilot.adapter.open_oscar_database` opens SQLite through a `mode=ro` URI, enables `query_only`, begins an explicit read transaction, validates schema identity, and always closes the connection.
- Schema version 17 is the only supported OSCAR schema; missing metadata and all other versions fail before the connection is exposed to extraction code.
- `pap_pilot.adapter.extract_session_summary` returns one immutable raw adapter record containing schema, profile, machine, session-boundary, six-setting, and profile-scoped channel provenance.
- `pap_pilot.adapter.extract_session_events` returns only the six allowlisted machine-labeled/OSCAR-normalized event kinds for one validated session, with raw provenance and explicitly unknown completeness.
- `pap_pilot.adapter.extract_flow_rate_signal` returns the selected session's raw 25 Hz `FlowRate` EventLists as separate immutable segments with raw timestamps, L/min values, gaps, storage/checksum provenance, and explicit missing-data state.
- `pap_pilot.adapter.extract_mask_pressure_signal` returns only the selected session's raw 25 Hz `MaskPressureHi` EventLists as separate immutable segments with raw timestamps, cm H₂O values, gaps, storage/checksum provenance, and explicit missing-data state.
- `pap_pilot.adapter.extract_leak_signal` returns only the selected session's stored sparse `Leak` updates as separate immutable EventLists with raw unsigned timestamp deltas, raw timestamps, L/min values, gaps, combined value/time storage provenance, checksum validation, explicit missing-data state, and the OSCAR-resolved `unintentional` source semantic.
- `docs/research/oscar-reference-night-cross-check.md` records explicit passes for settings, session boundaries, event counts, and all three required signals' timing, values, units, display relationships, and Leak semantics on one private reference night.
- Milestone 1 was accepted on September 1, 2026: required AirCurve 10 ASV sessions, settings, events, Flow Rate, Mask Pressure, and Leak extract reproducibly through the strictly read-only adapter without modifying OSCAR data.
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

S14C — Cross-check remaining signals and accept Milestone 1.

## Validation performed

- Ran `PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover --start-directory tests --verbose`; all forty-two tests passed without resource warnings after resolving the Leak semantic enum.
- Reselected the private reference night locally using its one-enabled-session OSCAR-day constraint and extracted Flow Rate, Mask Pressure, and Leak from the same session. Only named boolean contracts were emitted; no profile, therapy date, identifier, setting, count, timestamp, sample value, extrema, or checksum was printed or retained.
- `MaskPressureHi` passed exact EventList/cache count and outer-bound comparisons, exact 40 ms generated timing, OSCAR-cache extrema comparisons within `1e-5`, physical graph-range checks, cm H₂O unit checks, gain/zero-offset checks, and exact per-segment synchronization with Flow Rate.
- `Leak` passed exact stored-update/cache count and outer-bound comparisons, unsigned delta-derived timing and monotonicity checks, OSCAR-cache extrema comparisons within `1e-5`, physical graph-range checks, L/min unit checks, gain/zero-offset checks, and confirmation that the adapter returns stored updates without inferred holds.
- Pinned OSCAR source commit `64c5e90a26f91fb15868bcfcccde0c1e1522ac86` establishes that the Mask Pressure graph substitutes `MaskPressureHi` when present, sparse Leak display follows the square-wave graph preference, and ResMed `Leak` maps to the unintentional/excess `CPAP_Leak` channel rather than the distinct total-leak channel.
- Confirmed OSCAR was closed before and after validation. The source and protected `0400` disposable copy matched byte-for-byte before and after guarded `mode=ro&immutable=1` access, neither the live directory nor copy gained SQLite sidecars, and both the private copy and temporary OSCAR source checkout were removed.
- Reviewed every Milestone 1 work item and its exit criterion. The official-demo run is recorded, the required schema subset is mapped, the adapter is strictly read-only and version-gated, and the selected sessions/settings/events/signals are reproducible. The gate is accepted with no discrepancy blocking Milestone 2.

- Ran `PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover --start-directory tests --verbose`; all forty-two tests passed without resource warnings.
- The deterministic schema-17 fixture reproduced two independent sparse `Leak` EventLists, five stored updates, exact unsigned 32-bit millisecond-delta timestamps, L/min gain/offset conversion, source identifiers, and machine-recorded/OSCAR-normalized provenance.
- Repeated Leak extraction produced exactly equal immutable output. The fixture retained a positive inter-list gap, did not create step-hold samples, and decoded both uncompressed and Qt `qCompress` value/time BLOB pairs.
- Focused tests confirmed missing Leak channel and missing EventLists produce distinct explicit availability states, while a missing data row, profile mismatch, checksum mismatch, combined storage-size mismatch, timestamp-length mismatch, nonmonotonic timestamps, noncontiguous EventList index, or non-absent source dimension fails safely. Extraction left the source fixture unchanged.
- Protected-copy inspection corrected two schema-17 mapping details: Leak `dimension` is SQL `NULL` in the scoped copy, and `data_size`/`compressed_size` cover the value and timestamp BLOBs together. The adapter accepts only `NULL` or empty source dimension, preserves the exact value, and validates the individual `count*2` and `count*4` arrays plus combined metadata.
- Confirmed OSCAR was closed and the live database had no WAL/SHM sidecars before making a fresh protected copy outside the repository. Source and copy matched byte-for-byte before access, and the copy was protected as file mode `0400` inside a mode-`0500` directory.
- Used the guarded `mode=ro&immutable=1` opt-in only on that trusted copy. One locally selected compatible session passed Leak channel identity, L/min canonical unit, stored timestamp formula/bounds, finite values, EventList gaps, combined storage integrity, checksum validation, source provenance, deterministic output, and unresolved semantics checks; only boolean contract results were emitted.
- Reconfirmed OSCAR remained closed, source and copy bytes still matched, and no copy sidecars were created. The disposable copy was removed and its absence verified. No profile, therapy date, session identifier, timestamps, counts, Leak values, settings, or checksums were emitted or retained.
- Leak SQL is restricted by one validated session and its profile-scoped `Leak` channel. It does not query Mask Pressure, Flow Rate, leak thresholds, quality classifications, metrics, other sessions, or derived OSCAR channels.

- Ran `PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover --start-directory tests --verbose`; all thirty-one tests passed without resource warnings.
- The deterministic schema-17 fixture reproduced two independent `MaskPressureHi` EventLists, five total samples, exact 40 ms timestamps and end-exclusive ranges, the `cmH2O` source dimension normalized to cm H₂O, per-list gain/offset conversion, source identifiers, and machine-recorded/OSCAR-normalized provenance.
- Repeated Mask Pressure extraction produced exactly equal immutable output. The fixture retained an explicit positive inter-list gap and decoded both an uncompressed primary BLOB and a Qt `qCompress` BLOB without concatenating or interpolating the segments.
- Focused tests confirmed missing Mask Pressure channel and missing EventLists produce distinct explicit availability states, while a missing data row, profile mismatch, checksum mismatch, noncontiguous EventList index, or wrong source dimension fails safely. Extraction left the source fixture unchanged.
- The uniform waveform decoder is now shared internally by Flow Rate and Mask Pressure while their public records retain signal-specific value, gain, offset, unit, availability, and error fields. Existing Flow Rate tests passed unchanged after the refactor.
- Confirmed OSCAR was closed and the live database had no WAL/SHM sidecars before making a fresh protected copy outside the repository. Source and copy matched byte-for-byte before access, and the copy was protected as file mode `0400` inside a mode-`0500` directory.
- Used the guarded `mode=ro&immutable=1` opt-in only on that trusted copy. One locally selected compatible session passed exact `MaskPressureHi` channel identity, 25 Hz timing, cm H₂O source/canonical units, sample shape, in-session boundaries, explicit gaps, finite values, storage/checksum validation, and source-provenance checks; only boolean contract results were emitted.
- Reconfirmed source and copy bytes still matched, no copy sidecars were created, and the disposable copy and validation helper were removed. No profile, therapy date, session identifier, timestamps, counts, pressure values, settings, or checksums were emitted or retained.
- Mask Pressure SQL is restricted by one validated session and its profile-scoped `MaskPressureHi` channel. It does not query `Leak`, sparse `Pressure`, other signals, metrics, other sessions, or perform Flow/Pressure alignment analysis.

- One locally selected OSCAR day with exactly one enabled session passed all four S14 domains: settings, session boundaries, event counts, and Flow Rate.
- All six S11 settings exactly matched their OSCAR source rows and were present in OSCAR's built-in Device Settings report; ASV mode encodings and the cm H₂O pressure contract matched.
- S11 start/end boundaries and duration exactly matched OSCAR session/day report sources. S12 OA, CA, UA, H, and RERA counts matched both session and daily summaries, and all six allowlisted kinds including Large Leak matched session-channel counts; `AllApnea` remained excluded.
- S13 Flow Rate sample count/time range matched OSCAR's cache, every EventList was 25 Hz, decoded observed extrema matched OSCAR's single-precision cache within `1e-5`, and all values remained inside OSCAR's declared physical graph range.
- The selected Flow Rate EventLists had zero offset and gain matching OSCAR's cache. OSCAR's ResMed loader, signed EventList storage, and line-chart code confirmed that PAP Pilot's decoded values match OSCAR's graph formula for this session. Official OSCAR chart documentation confirmed L/min and positive-inspiration/negative-expiration display behavior.
- The selected profile, date, identifiers, settings, counts, timestamps, values, and checksums were not emitted or committed. OSCAR was closed before copying; only protected disposable copies were inspected.
- macOS denied Accessibility and screen capture access to the disposable OSCAR GUI. The cross-check therefore used OSCAR's built-in database report queries/caches and current graph source path; no screenshot or pixel-level tooltip comparison was retained.

- The deterministic schema-17 fixture reproduced two independent `FlowRate` EventLists, five total samples, exact 40 ms timestamps and end-exclusive ranges, the `L/M` source dimension normalized to L/min, per-list gain/offset conversion, source identifiers, and machine-recorded/OSCAR-normalized provenance.
- Repeated extraction produced exactly equal immutable output. The fixture retained an explicit positive inter-list gap and decoded both an uncompressed primary BLOB and a Qt `qCompress` BLOB without concatenating or interpolating the segments.
- Focused tests confirmed missing channel and missing EventLists produce distinct explicit availability states, while a missing data row, profile mismatch, checksum mismatch, or noncontiguous EventList index fails safely. Extraction left the source fixture unchanged.
- Qt's official documentation identifies `qChecksum`'s default as the ISO 3309 CRC-16-CCITT algorithm and documents the four-byte big-endian `qCompress` length header. A sanitized probe confirmed the ISO-3309/X-25 implementation against an OSCAR checksum before the probe was removed.
- Confirmed OSCAR was closed and the live database had no WAL/SHM sidecars before making a fresh copy outside the repository. Source and copy matched byte-for-byte before access, then the copy was protected as file mode `0400` inside a mode-`0500` directory.
- Used the guarded `mode=ro&immutable=1` opt-in only on that trusted fixed copy. One locally selected session with `FlowRate` passed one-session/profile/channel provenance, EventList boundary, 25 Hz timing, L/min unit, sample-count, time-range, gap, storage-integrity, checksum, and source-class checks; only contract field names and boolean results were emitted.
- Reconfirmed OSCAR remained closed, live and copy sidecars remained absent, and source/copy bytes still matched. The private disposable copy was then removed and its absence verified.
- Signal SQL is restricted by one `sessions.id` and its profile-scoped `FlowRate` channel. It does not query `MaskPressureHi`, `Leak`, cached signal summaries, event rows, metrics, other sessions, or derived OSCAR channels.
- `git diff --check` passed.

## Decisions and assumptions

- Only one Codex goal/sprint should be active at a time.
- Sprints deliberately stop at their stated completion check.
- Undiscovered work becomes a new queued sprint rather than silently expanding an active sprint.
- Repository prose is not hard-wrapped at a fixed column. Markdown paragraphs and list items stay on one logical line, with line breaks reserved for semantic structure and literal blocks.
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
- Pressure settings normalize to cm H₂O and retain decimal precision. S14 confirmed that unit contract against OSCAR for the reference night despite the absence of a database unit column.
- Schema-17 respiratory-event identity is derived only from `(profile_id, channel_id) → channels.channel_code`; the raw `respiratory_events.event_type` is retained as opaque provenance and never decoded with the schema-16 enum.
- The first experiment's event allowlist is OA, CA, UA, H, RERA, and Large Leak. `AllApnea` is excluded to prevent aggregate/component double-counting, and CSR, periodic breathing, user flags, and signal data remain out of scope.
- Event-row absence remains unknown rather than zero because the observed `events_loaded` flag is inconsistent with row presence. S14 established reference-night count agreement, not universal event completeness.
- Non-contained Large Leak spans remain raw and flagged. S14 count agreement does not authorize clipping, reassignment, or reinterpretation of those rows.
- The user reaffirmed that PAP Pilot must provide additional deterministic analysis rather than merely reproduce OSCAR outputs. Machine/OSCAR events and derived channels are comparison/reference inputs, not authoritative companion metrics.
- The user directed that the two remaining required-signal extractions and their milestone cross-check be added as three bounded sprints before S15. Suffix identifiers S14A–S14C preserve all existing sprint identifiers and dependencies.
- The S14 OSCAR cross-check validates import equivalence only. It does not make OSCAR summaries into PAP Pilot analysis; later metrics remain independently calculated in the deterministic engine from mapped source signals.
- For the reference night, S11 settings/boundaries, S12 counts, and S13 Flow Rate all pass their explicit OSCAR comparisons. No adapter change was justified by S14.
- OSCAR Flow Rate `session_channels.min/max` are observed single-precision extrema; comparisons use `1e-5` absolute tolerance. `phys_min/phys_max` describe the declared graph range, while `sum`, `avg`, and `wavg` are not populated as independently comparable Flow Rate waveform statistics.
- The scoped Flow Rate lists have zero offset, making PAP Pilot's `raw * gain + offset` conversion identical to OSCAR's graph's raw-times-gain rendering for this reference session. The positive/negative sign convention is now established for this source; it is not a derived breath-phase classification.
- `FlowRate` and `MaskPressureHi` share only private uniform-waveform storage decoding. Their public adapter records remain signal-specific so pressure cannot be consumed as flow by field-name coincidence.
- `MaskPressureHi` is allowlisted explicitly, requires schema-17 waveform type 0, exact `cmH2O` source dimension, 40 ms sample interval, signed little-endian 16-bit primary values, per-EventList gain/offset, and valid Qt ISO-3309/X-25 checksum provenance.
- Mask Pressure EventLists remain independent segments with explicit gaps and missing states. S14A does not align them with Flow Rate or derive pressure-support response; those are later analysis concerns.
- The minimum S08 input set is `FlowRate`, `MaskPressureHi`, and `Leak`. OSCAR/device-derived AHI, flow limitation, respiratory rate, tidal volume, minute ventilation, target ventilation, Ti, and Te are excluded from the required set and cannot silently substitute for PAP Pilot calculations.
- `MaskPressureHi` is the required pressure input because it is a 25 Hz waveform synchronized with flow. Sparse `Pressure`, low-resolution `MaskPressure`, and `EPAP` traces are not silent fallbacks.
- Flow and mask-pressure waveform timestamps derive from `first_time + i*rate`; their observed schema-17 `last_time` is end-exclusive. Leak timestamps derive only from the stored unsigned millisecond-delta array.
- EventLists remain separate segments. Missing signals and inter-list gaps are explicit quality state; the adapter never interpolates across them, carries a sparse value across a gap, or substitutes `session_channels` summaries for samples.
- `compressed_size` cannot determine whether a row is compressed in schema 17. Decode selection uses `compression_method` plus the mutually exclusive raw/compressed BLOBs, followed by length and checksum validation.
- The scoped ResMed `Leak` trace is unintentional/excess leak, not total leak. OSCAR maps the ResMed signal to `CPAP_Leak`, defines `CPAP_LeakTotal` separately as including natural mask leakage, and derives `CPAP_Leak` by subtracting expected mask vent leak only when an unintentional channel is absent.
- Schema-17 sparse Leak timestamps come only from the stored little-endian unsigned 32-bit millisecond-delta array; `rate` must be zero, deltas must be nondecreasing and span the EventList bounds, and the adapter returns no inferred step-hold samples.
- Leak values decode from little-endian signed 16-bit integers using each EventList's stored gain and offset. The database source dimension is absent (`NULL` in the scoped copy; empty string is also accepted as absent), while the canonical L/min unit is established by OSCAR's schema, ResMed loader, and graph path.
- For sparse Leak, `event_lists.data_size` is `count*6` and covers both uncompressed arrays; `compressed_size` covers both selected storage BLOBs. Individual value/time lengths and the combined metadata are all validated, while the stored checksum applies to the primary value array.
- Leak EventLists remain separate with raw gaps. Missing Leak means unavailable quality evidence rather than zero leak. The adapter exposes the source semantic as `unintentional`; later quality rules still must decide whether any interval is usable and must not equate the raw trace with PAP Pilot analysis.
- The initial Python scaffold uses a `src` layout, setuptools as its build backend, Python 3.11 or newer, and no runtime dependencies.
- The `pap_pilot.adapter` namespace owns external data access, while `pap_pilot.engine` owns deterministic companion analysis; OSCAR-derived results must not cross that boundary as if they were PAP Pilot calculations.
- The smoke test uses Python's standard-library `unittest` so the scaffold does not introduce a test-framework dependency before one is needed.
- Guarded OSCAR access uses two independent controls: SQLite URI `mode=ro` protects the main database, while `PRAGMA query_only=ON` also prevents writes to temporary tables during normal adapter use.
- The wrapper begins a read transaction before selecting `MAX(schema_version.version)`, accepts only integer version 17, and closes the connection on success or failure.
- The wrapper does not silently add `immutable=1`; that flag remains restricted to a trusted, fixed disposable copy and must never be used against the live OSCAR database.
- `trusted_immutable_copy=True` is an explicit caller assertion used only for a fixed copy made with OSCAR closed; ordinary guarded access remains `mode=ro` without silently bypassing SQLite change detection.
- S11 output is a raw, OSCAR-specific adapter record. It does not preempt the versioned normalized records assigned to S15.
- Session selection is by exactly one `sessions.id`. The extractor does not list nights, carry settings from another session, derive an OSCAR day, apply device-time corrections, or combine split sessions.
- A usable S11 session must belong to an active profile with agreeing timezone sources, have valid positive raw boundaries, be enabled and non-summary, report settings present, and contain all six required profile-scoped setting rows.
- Only fixed-EPAP ASV mode codes `PAPMode=6` and `RMS9_Mode=7` are accepted. PS Min must not exceed PS Max, and stored Max IPAP must agree with EPAP plus PS Max; S14 confirmed the pressure-unit contract for the reference night.
- Profile name and machine serial are retained only in the local raw result for provenance and are never included in ordinary diagnostics, committed fixtures, or sanitized validation output.
- The real validation session was selected locally without printing or retaining its identifier, therapy date, profile name, serial number, or setting values. Later reference-night work must reselect locally until S17 defines a safe retained fixture.
- S12 events remain raw adapter/reference data, not PAP Pilot analytical findings. Their explicit source class is `machine_labeled_oscar_normalized`.
- Schema-17 event identity comes only from the profile-scoped channel registry: `Obstructive`, `ClearAirway`, `Apnea`, `Hypopnea`, `RERA`, and `LeakSpan`. `event_type` is preserved as an opaque integer and never decoded with the contradicted schema-16 enum.
- `AllApnea` and every non-allowlisted channel are excluded from extraction and observed counts. S14 confirmed reference-night count agreement, but raw event completeness remains explicitly `unknown` because agreement for one night is not a universal completeness guarantee.
- Event starts/ends remain raw Unix epoch milliseconds, durations remain integer seconds, and the exact millisecond/second relationship is validated. Non-contained rows are retained unchanged and flagged rather than clipped, reassigned, or silently discarded.
- Event extraction reuses the S11 validation in the same read transaction and queries exactly one session database identifier. It does not derive corrected display times, OSCAR-day grouping, rates, indices, or any companion metric.
- The real S12 validation session was selected locally without printing or retaining its identifier, date, event kinds present, event counts, raw timestamps, profile/device provenance, or setting values.
- S13 extracts only schema-17 `FlowRate`; `MaskPressureHi`, `Leak`, all other signals, and every derived calculation remain outside this sprint.
- Flow output remains machine-recorded/OSCAR-normalized source data for later independent PAP Pilot analysis. The adapter performs binary decoding and unit conversion only; it does not segment breaths, interpret sign, calculate metrics, smooth, resample, baseline-correct, or fill gaps.
- Flow EventLists remain separate, zero-based contiguous segments. Timestamps are generated as `first_time + i * rate`, `last_time` is validated as the end-exclusive boundary, and a 40 ms interval is required for the selected 25 Hz schema-17 signal.
- Primary values decode as little-endian signed 16-bit integers and convert with each EventList's stored gain and offset. The `L/M` source dimension is preserved while the canonical unit is exposed as L/min.
- `event_data.compression_method`, not `compressed_size`, selects the mutually exclusive raw or Qt-zlib BLOB. Both branches require exact uncompressed length, supported field layout, and a matching Qt ISO-3309/X-25 checksum; `compressed_size` remains validated provenance.
- Missing profile channel and missing session EventLists are distinct explicit availability states. Malformed timing, provenance, indexing, storage, compression, dimensions, secondary fields, or checksums fail without partial output.
- The real S13 validation session was selected locally without printing or retaining its identifier, date, segment or sample counts, timestamps, sample values, signal extrema, profile/device provenance, settings, or checksums.

## Blockers

- No blocker prevents starting S15.
- Milestone 1 is accepted; its reference-night result is deliberately limited to one device/night and does not substitute OSCAR summaries for PAP Pilot's later independent analysis.
- The local database is schema v17 while the published data dictionary stops at v16. Later sprints must keep version-gating observed behavior and must not assume version equivalence.
- The contradictory respiratory-event enum, unreliable `events_loaded` flag, and non-contained Large Leak spans remain handled explicitly by S12 extraction; reference-night count agreement does not redefine those raw provenance rules.
- S13–S14C preserve waveform gaps/missing lists and treat `compressed_size` only as validated provenance. Flow Rate, Mask Pressure, and Leak display relationships are cross-checked, and the scoped Leak subtype is resolved as unintentional/excess.
- The empty local correction table and invalid raw session boundaries remain explicit inputs to later guarded-connection, session-extraction, and structural-quality work.

## Resume instruction

```text
Read AGENTS.md, Plan.md, SPRINTS.md, and STATUS.md. Complete only S15. Define the versioned normalized core records for nights, sessions, settings, events, signals, and provenance with deterministic serialization and provenance-preserving round trips. Do not implement adapter mapping, quality rules, fixtures, persistence, experiments, UI, or AI. Update SPRINTS.md and STATUS.md, commit, verify a clean tree, then stop.
```
