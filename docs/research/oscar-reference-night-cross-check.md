# OSCAR reference-night cross-check

**Cross-check date:** August 31, 2026

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

Overall result: **pass**. No S11–S13 adapter change was required.

## OSCAR behavior used for the signal comparison

The current OSCAR source provides a second, independent description of the installed data path:

- the [ResMed BRP loader](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/loader_plugins/resmed_loader.cpp#L3369) converts Flow Rate to L/min, retains the EDF gain/offset, and adds signed waveform samples;
- OSCAR's [EventList implementation](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/SleepLib/event.cpp#L57) stores signed 16-bit values and applies gain while calculating waveform extrema; and
- the [line-chart renderer](https://gitlab.com/CrimsonNape/OSCAR-code/-/blob/64c5e90a26f91fb15868bcfcccde0c1e1522ac86/oscar/Graphs/gLineChart.cpp#L753) plots waveform samples from raw storage and gain.

The OSCAR chart guide documents Flow Rate in L/min and explains that flow above zero is inspiration while flow below zero is expiration: [OSCAR Chart Organization](https://www.apneaboard.com/wiki/index.php?title=OSCAR_Chart_Organization).

## Bounded discrepancies and limitations

- macOS denied Accessibility inspection and screen capture for the disposable OSCAR GUI process. Consequently this sprint did not retain a screenshot or perform pixel-level tooltip comparison. It instead cross-checked OSCAR's built-in database report queries/caches and the graph code path used to render the same EventLists.
- `session_channels.sum`, `avg`, and `wavg` are not usable waveform-value comparators for Flow Rate. OSCAR deliberately skips those summary calculations for high-resolution waveform channels. `phys_min/phys_max` are the declared physical display range, not observed extrema. The authoritative observed comparison is `min/max`, using OSCAR's float precision.
- This result covers only the selected reference night and only the first S13 signal. It does not establish Leak subtype semantics, validate another device/night, add metrics, or perform any independent clinical analysis.
