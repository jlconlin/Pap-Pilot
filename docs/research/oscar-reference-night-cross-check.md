# OSCAR reference-night cross-check

**Cross-check date:** August 31–September 1, 2026

**Installed OSCAR:** 2.0.0

**Database schema:** 17

**Scope:** one locally selected OSCAR day containing one enabled session

## Privacy and safety

OSCAR was closed before the source database was copied. All extraction and comparison work used a protected disposable copy opened with the guarded read-only adapter and `immutable=1`; the live database was never opened by PAP Pilot. The selected profile, therapy date, database identifiers, setting values, event counts, timestamps, waveform values, and checksums were neither printed nor retained in this repository.

This cross-check compares imported source data only. OSCAR settings, event labels, caches, and graph behavior remain reference evidence; they do not become PAP Pilot metrics or conclusions. PAP Pilot's later breath and outcome analysis must still be computed independently from source signals.

## Result

| Domain | Result | Explicit comparison |
|---|---|---|
| Settings | **Pass** | All six S11 settings exactly matched their OSCAR schema-17 source rows and were present in OSCAR's built-in **Device Settings** report result. The two ASV mode encodings matched the scoped mapping, and pressure values use the OSCAR cm H₂O display contract. |
| Session boundaries | **Pass** | The S11 raw start, raw end, and derived duration exactly matched OSCAR's session/day report sources. The selected OSCAR day contained exactly one enabled session, so no split-night aggregation was involved. |
| Event counts | **Pass** | S12 OA, CA, UA, H, and RERA counts exactly matched both OSCAR session and daily summary caches. All six allowlisted kinds, including Large Leak, matched the profile-scoped session-channel counts. `AllApnea` remained excluded, preventing aggregate/component double-counting. |
| Flow Rate | **Pass** | S13 sample count and time range exactly matched OSCAR's Flow Rate cache; every list was 40 ms/sample (25 Hz). Decoded observed extrema matched OSCAR's cached extrema within `1e-5`, appropriate for OSCAR's single-precision event values, and stayed within OSCAR's physical display range. The selected lists had zero offset and a gain matching OSCAR's cache, so PAP Pilot's `raw * gain + offset` values are identical to OSCAR's graph path for this session. The signal uses L/min and contains both signs under OSCAR's positive-inspiration/negative-expiration display convention. |
| Mask Pressure | **Pass** | S14A sample count, outer time range, 40 ms timing, and decoded extrema exactly matched OSCAR's `MaskPressureHi` cache within `1e-5`; all values stayed within OSCAR's physical graph range. Every segment matched the corresponding Flow Rate EventList index, bounds, count, and rate. The selected lists had zero offset and a gain matching OSCAR's cache. The stored `cmH2O` dimension and PAP Pilot's canonical cm H₂O unit agree with OSCAR's Mask Pressure channel, and OSCAR substitutes `MaskPressureHi` into its Mask Pressure graph when the high-resolution channel is present. |
| Leak | **Pass** | S14B stored-update count, outer time range, unsigned millisecond-delta timing, and decoded extrema exactly matched OSCAR's `Leak` cache within `1e-5`; all values stayed within OSCAR's physical graph range. The selected lists had zero offset and a gain matching OSCAR's cache. The database dimension is absent, but the profile-scoped channel, OSCAR schema, ResMed loader, and graph all identify the unit as L/min. PAP Pilot returns only recorded updates; OSCAR connects those updates as either a step trace or straight segments according to the user's square-wave graph preference, without turning the source EventLists into a uniform waveform. |
| Leak semantics | **Pass** | The selected ResMed channel is unintentional/excess leak, not total leak. OSCAR maps ResMed's `Leak` signal to `CPAP_Leak`, defines the separate `CPAP_LeakTotal` channel as including natural mask leakage, and calculates `CPAP_Leak` from total leak by subtracting the expected mask-vent baseline only when an unintentional channel is absent. The adapter now exposes the source semantic as `unintentional`; this is imported-source metadata, not a PAP Pilot quality judgment. |

Overall result: **pass**. No sample, timing, unit, or segment behavior required correction. The only adapter change was replacing S14B's deliberately unresolved Leak semantic with the now-evidenced `unintentional` source meaning.

## OSCAR behavior used for the signal comparison

Pinned OSCAR source commit `64c5e90a26f91fb15868bcfcccde0c1e1522ac86` provides a second, independent description of the installed data path:

- the [ResMed BRP loader](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/loader_plugins/resmed_loader.cpp#L3369) converts Flow Rate to L/min, retains the EDF gain/offset, and adds signed waveform samples;
- the same [BRP loader](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/loader_plugins/resmed_loader.cpp#L3376) maps the high-resolution ResMed mask-pressure signal to `CPAP_MaskPressureHi`, retains its dimension and gain/offset, and stores it as a uniformly sampled waveform;
- the [channel schema](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/schema.cpp#L240) links `CPAP_MaskPressureHi` to Mask Pressure and assigns cm H₂O, while the [line chart](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/Graphs/gLineChart.cpp#L148) substitutes that high-resolution channel when it exists;
- the [ResMed loader](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/loader_plugins/resmed_loader.cpp#L3619) maps the device's `Leak` signal to `CPAP_Leak`, converts it to L/min, and stores timed updates;
- the [channel schema](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/schema.cpp#L258) defines `CPAP_Leak` separately from [`CPAP_LeakTotal`](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/schema.cpp#L286), whose description explicitly includes natural mask leakage;
- OSCAR's [leak calculation](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/calcs.cpp#L1288) leaves an existing `CPAP_Leak` channel unchanged and otherwise derives it from `CPAP_LeakTotal` by subtracting the expected mask leak, establishing `CPAP_Leak` as unintentional/excess leak;
- OSCAR's [EventList implementation](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/event.cpp#L57) stores signed 16-bit values and applies gain while calculating waveform extrema; and
- the [line-chart renderer](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/Graphs/gLineChart.cpp#L639) distinguishes uniform waveforms from timed EventLists, disables square plotting for waveforms, and draws sparse samples as optional horizontal-then-vertical steps when the square-wave preference is enabled.

The OSCAR chart guide documents Flow Rate in L/min and explains that flow above zero is inspiration while flow below zero is expiration: [OSCAR Chart Organization](https://www.apneaboard.com/wiki/index.php?title=OSCAR_Chart_Organization).

## Bounded discrepancies and limitations

- macOS denied Accessibility inspection and screen capture for the disposable OSCAR GUI process. Consequently this sprint did not retain a screenshot or perform pixel-level tooltip comparison. It instead cross-checked OSCAR's built-in database report queries/caches and the graph code path used to render the same EventLists.
- `session_channels.sum`, `avg`, and `wavg` are not usable waveform-value comparators for the high-resolution signals. OSCAR deliberately skips those summary calculations for waveform channels. `phys_min/phys_max` are the declared physical display range, not observed extrema. The authoritative observed comparison is `min/max`, using OSCAR's float precision.
- The selected signal lists all have zero offset. That makes PAP Pilot's `raw * gain + offset` conversion agree with every relevant OSCAR rendering branch for this night, but this cross-check does not establish equivalence for a future nonzero-offset EventList.
- This result covers only the selected reference night. It does not validate another device/night, define leak-quality thresholds, add metrics, or perform any independent clinical analysis.

## Milestone 1 gate

| Exit evidence | Result | Review |
|---|---|---|
| Official SQL demonstration run | **Complete** | S05 ran the unmodified official demonstrator against a protected copy and recorded its repeatable read-only failure before schema/profile access. That upstream failure is bounded evidence about the demonstrator, not a failure of PAP Pilot's adapter. |
| Required schema subset documented | **Pass** | S06–S08 document schema-17 identity/session provenance, fixed-EPAP ASV settings/events, and the three minimum signals with version gates, units, encodings, timing, and missing-data behavior. |
| Strictly read-only adapter | **Pass** | S10 opens only `mode=ro`, sets `query_only`, validates schema 17, and permits `immutable=1` only through an explicit trusted-copy option. Protected-copy validation before and after extraction remained byte-for-byte identical and produced no sidecars. |
| Required sessions, settings, and events reproducible | **Pass** | S11 and S12 focused tests and the reference-night comparison establish stable raw session/setting output and allowlisted event output matching OSCAR's caches/report sources. |
| Required signals reproducible | **Pass** | S13, S14A, and S14B focused tests establish deterministic Flow Rate, Mask Pressure, and Leak extraction. This cross-check establishes their timing, values, units, display relationship, synchronization where required, and Leak meaning against OSCAR. |
| Safety and analysis boundary | **Pass** | Every real-data check used a protected disposable copy made while OSCAR was closed; the live database was never opened by PAP Pilot. OSCAR data remains imported evidence only, and PAP Pilot has not adopted OSCAR's derived summaries as its own analysis. |

**Gate decision: Milestone 1 accepted on September 1, 2026.** The exit criterion is satisfied: the required AirCurve 10 ASV signals, settings, sessions, and events are extracted reproducibly without modifying OSCAR data. No discrepancy blocks Milestone 2.
