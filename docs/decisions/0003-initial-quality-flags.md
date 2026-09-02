# 0003 — Initial quality flags and insufficient-evidence behavior

**Status:** Accepted

**Date:** September 2, 2026

**Rule-set identifier:** `pap-pilot.quality`

**Rule-set version:** 1

## Context

PAP Pilot needs deterministic quality findings before it calculates companion metrics or evaluates an experiment. The normalized model preserves source signals, sessions, events, gaps, and provenance but deliberately makes no quality judgment. Quality processing must identify where evidence is usable, where a known problem exists, and where the available data cannot support an answer.

This decision defines the first rules for missing samples, short and split sessions, large leak, signal artifacts, clock corrections, and likely wake breathing. It does not implement the rules, define an experiment's required number of nights, choose objective metrics, classify an experiment, diagnose sleep or respiratory conditions, or turn machine/OSCAR labels into PAP Pilot conclusions.

## Evidence and limitations

The local schema and signal contracts are documented in `docs/research/oscar-identity-session-schema-map.md`, `docs/research/oscar-aircurve-asv-settings-events-map.md`, and `docs/research/oscar-aircurve-asv-signal-map.md`. Those contracts establish raw timestamps, independent EventList segments, explicit gaps, a sparse unintentional-leak signal, machine-labeled Large Leak spans, and the currently unverified schema-17 device-time-correction mapping.

ResMed's [Therapy Handbook](https://document.resmed.com/documents/us/10114280r1_ResMed_Therapy_Handbook_AMER_Eng_Digital_SinglePages.pdf) says unintentional leak on ResMed devices should remain below 24 L/min. The [AirCurve 10 ASV user guide](https://document.resmed.com/documents/products/machine/aircurve-series/user-guide/aircurve-10-asv_user-guide_amer_spa.pdf) states that measurement accuracy can be reduced by leaks and supplies the device's flow, leak, pressure, and timing accuracy context. These device-specific sources support a 24 L/min prototype threshold for the mapped ResMed unintentional-leak channel; the threshold is not generalized to total-leak signals or other manufacturers.

The AASM's [sleep-scoring update](https://aasm.org/wp-content/uploads/2017/11/Summary-of-Updates-in-v2.1-FINAL.pdf) bases wake and sleep-stage scoring on signals including EEG, EOG, and chin EMG that PAP Pilot does not have. Ayappa et al.'s [flow-irregularity study](https://pmc.ncbi.nlm.nih.gov/articles/PMC2625330/) supports irregular PAP-flow breathing as a possible wake/arousal marker but also shows that it misses wake and can produce false positives. PAP Pilot therefore labels only a provisional likely-wake-breathing candidate, never confirmed wake or sleep stage.

All numerical artifact and likely-wake parameters below are conservative engineering heuristics for the single-user prototype, not clinical thresholds. They must remain visible in provenance and require a rule-set version change if altered.

## Decision

### Quality is evidence, not a score

The engine will produce independent findings rather than one opaque night-quality score. A finding applies to one normalized record or one half-open interval `[start_time_ms, end_time_ms)` and contains at least:

- `rule_set_id` and `rule_set_version`;
- `rule_id` and a rule-specific parameter snapshot;
- the evaluated record identifier and, when applicable, exact raw-time interval;
- `status`;
- `impact`;
- source record and provenance identifiers;
- a stable reason code;
- measured supporting values with units when the rule calculates them; and
- limitations and affected analytical capabilities.

Every quality finding is companion-derived. It retains the source provenance it evaluated and never replaces or relabels machine-recorded, machine-labeled, or OSCAR-normalized data.

### Status and impact vocabularies

Each rule evaluation returns exactly one of these statuses for each evaluated scope:

| Status | Meaning |
|---|---|
| `pass` | All required inputs for this rule and scope were present and the version-1 condition was not observed. A pass applies only to this rule; it is not proof that the data are globally clean. |
| `flagged` | The rule observed its defined condition. The finding reports the affected interval or record and its evidence. |
| `insufficient_evidence` | A required input, coverage interval, provenance field, supported interpretation, or validated transformation was unavailable, so the rule cannot return pass or flagged for that scope. |
| `not_applicable` | The rule genuinely does not apply to the requested analysis or signal type. Missing evidence is never represented as not applicable. |

The independent `impact` field is one of `none`, `caution`, `exclude_interval`, `exclude_session`, or `block_requested_analysis`. A flagged condition does not automatically invalidate a whole night, and insufficient evidence does not erase a separately observed problem. Different intervals may have different statuses and impacts.

The version-1 rule and reason-code inventory is fixed as follows. `condition_not_observed` is the reason for a pass, and `rule_not_applicable` is the reason for not applicable.

| Rule ID | Flagged reason codes | Insufficient-evidence reason codes |
|---|---|---|
| `missing_required_signal` | `coverage_gap` | `channel_missing`, `data_missing`, `unsupported_signal_contract`, `no_common_eligible_interval` |
| `flow_pressure_misalignment` | `bounds_mismatch`, `sample_count_mismatch`, `sample_time_mismatch` | `paired_signal_unavailable` |
| `short_session` | `duration_below_300000_ms` | `session_bounds_unavailable` |
| `split_session_night` | `multiple_sessions` | `night_sessions_unavailable` |
| `clock_correction_integrity` | `supported_correction_present` | `correction_input_missing`, `correction_range_ambiguous`, `unsupported_drift`, `stacked_correction_unreproducible`, `corrected_timeline_invalid` |
| `large_leak` | `threshold_exceeded`, `machine_large_leak_span` | `leak_evidence_missing`, `unsupported_leak_contract` |
| `signal_artifact` | `digital_clipping`, `isolated_impulse` | `artifact_input_missing` |
| `likely_wake_breathing` | `irregular_breathing_candidate` | `wake_prerequisite_missing`, `too_few_eligible_breaths` |

### Propagation to requested analysis

Every later metric or experiment rule must declare the signals, session properties, time basis, and quality rules it requires. It operates only on the intersection of intervals that satisfy those requirements. It returns `insufficient_evidence` when no eligible interval remains or when a required whole-session/night determination is insufficient. It may not silently fill a gap, assume a missing leak value is zero, treat absent machine events as complete, infer sleep from mask-on time, or let a clean interval make an unevaluated interval pass.

S21 and later methodology decisions may define minimum usable duration for a particular metric or experiment. This rule set deliberately does not set minimum baseline nights, intervention nights, experiment sample sizes, or a universal valid-night duration.

## Version-1 structural rules

### `missing_required_signal`

Inputs are the requested analysis interval, its declared required signal kinds, each `SignalRecord` representation and unit, segment boundaries and closure, values/timestamps, and signal availability retained in provenance.

For a uniform waveform, coverage is the union of its half-open segment ranges. For sparse timed updates, evidence exists only at stored update times and on step intervals from one update to the next within the same EventList; the final update is a point observation and is never held past its segment boundary. Coverage never crosses a segment or session gap.

The rule is `flagged` with `exclude_interval` for every uncovered portion of a requested interval when the channel and some data exist. It is `insufficient_evidence` with `block_requested_analysis` when a required channel is missing, all its data are missing, its representation/unit is unsupported, or no common eligible interval remains. It is `pass` only when every required signal covers the complete requested scope under its own timing semantics.

Flow Rate is required for independent breath-level analysis. Mask Pressure is additionally required for synchronized pressure-response analysis. Leak is required to establish that an interval is below the version-1 large-leak threshold; missing leak makes leak quality unknown rather than clean.

### `flow_pressure_misalignment`

Inputs are Flow Rate and Mask Pressure uniform segments and their sample timestamps. The rule is `pass` only where both signals have the same half-open bounds, sample count, and sample timestamps. Any mismatch is `flagged` with `exclude_interval` for paired pressure-response analysis. If either signal is unavailable, the status is `insufficient_evidence` rather than misaligned.

### `short_session`

Inputs are a session's raw start and end times. Version 1 uses `short_session_threshold_ms = 300000` (five minutes). Duration below the threshold is `flagged` with `caution`; duration exactly at or above the threshold passes. Invalid, zero, or negative durations remain structural input errors and do not become quality findings.

The five-minute boundary is an engineering marker for a brief mask-fit, test, or interrupted start, not a claim about sleep adequacy, adherence, or a valid experiment night. A short session remains visible and is not silently deleted or automatically excluded. If a requested analysis needs more duration, that separate analysis returns insufficient evidence under its own versioned requirement.

### `split_session_night`

Input is the ordered session collection in one `NightRecord`. More than one session is `flagged` with `caution`; one session passes. The finding records each session identifier and each inter-session gap. Signal data and sparse values are never joined, interpolated, or held across the gap.

A split night is not automatically invalid. Each session and continuous eligible interval is evaluated independently, and later aggregation must disclose which sessions it included. Inconsistent settings or an unconfirmed experiment boundary are handled by later allocation rules, not hidden inside this quality flag.

### `clock_correction_integrity`

Inputs are the raw session/signal/event timestamps, the session's OSCAR day, every active schema-17 correction row applicable to the machine/day, the exact version-gated correction interpretation, and a separately retained corrected timeline when one is supported.

The rule passes for raw-duration and within-session alignment work when the adapter confirms either that no active correction applies or that all involved source records share the same raw time basis. A supported, fully verified correction is surfaced as a `flagged` finding with `caution`, including its type and magnitude, while raw and corrected times remain separate.

The rule returns `insufficient_evidence` with `block_requested_analysis` for corrected wall-clock/date analysis when correction rows were not queried, range applicability is ambiguous, required fields are missing, a drift formula has not passed synthetic boundary tests, stacked corrections cannot be reproduced, or correction would reorder or desynchronize records. A constant offset does not alter duration; an unresolved wall-clock correction does not automatically block calculations that use only common raw relative time.

Normalized record version 1 does not yet carry a verified correction collection or corrected timeline. Until S19 supplies and tests that input, corrected wall-clock/date conclusions are therefore insufficient; the absence of correction data in a normalized record is not proof that no correction exists.

## Version-1 signal rules

### `large_leak`

Inputs are the unintentional `leak_rate` signal in L/min, its sparse update timing and segment boundaries, and every observed machine-labeled `large_leak` event with its source completeness state.

Version 1 uses `large_leak_threshold_l_min = 24.0`. A sparse value at or above 24.0 L/min marks the half-open step interval from that update to the next update within the same EventList. The final update is retained as point evidence but is not extended past the list. Every machine-labeled Large Leak event with positive overlap is also flagged after intersecting it with the session boundary; non-contained raw event bounds remain in provenance and zero-overlap events do not contaminate the session.

Threshold-derived and machine-labeled intervals are unioned for exclusion while retaining both evidence classes. Every affected interval is `flagged` with `exclude_interval` for flow morphology, event-rate, pressure-response, and other analyses whose accuracy depends on reliable flow. Large leak does not invalidate unaffected intervals or the whole night by itself.

If the leak channel, semantic, unit, or all data are missing, the rule is `insufficient_evidence`. Gaps in an otherwise available leak trace are insufficient only for those gaps. Observed Large Leak events are still flagged even when the trace is missing. An absent Large Leak event never establishes pass because event completeness is unknown; a fully covering compatible leak trace below threshold can establish a threshold-based pass for its covered interval.

### `signal_artifact`

Inputs are a continuous Flow Rate or Mask Pressure waveform, its unit and 40 ms timing, and the source gain/offset values required to reconstruct signed 16-bit raw values. Import-level decompression, byte-length, checksum, non-finite-value, or timestamp-integrity failures remain hard adapter/model errors and block normalization; they are not softened into quality flags.

Version 1 flags `digital_clipping` when a reconstructed raw sample equals `-32768` or `32767`. It flags an `isolated_impulse` only for an interior sample with contiguous neighbors when both jumps from the center meet the signal threshold and the two neighbors agree within the neighbor tolerance:

| Signal | Center-to-each-neighbor threshold | Neighbor-to-neighbor tolerance |
|---|---:|---:|
| Flow Rate | 30 L/min | 3 L/min |
| Mask Pressure | 3 cm H₂O | 0.3 cm H₂O |

The affected half-open interval is `[t_(i-1), t_(i+2))`, covering the sample before the candidate, the candidate sample, and the sample after it; the segment's end boundary supplies `t_(i+2)` when the following sample is the segment's final sample. A finding is `flagged` with `exclude_interval`; it means the interval is unsuitable for automated high-resolution morphology, not that the underlying physiological event is known to be false.

The rule deliberately does not call a flat or near-zero flow interval an artifact because apnea, mask-off time, or true low flow may look flat. It does not treat coughs, sighs, movement, irregular breathing, large leak, or a jump across separate EventLists as artifact without the exact version-1 condition. If required gain/offset provenance or sufficient contiguous samples is absent, the relevant detector returns `insufficient_evidence`.

### `likely_wake_breathing`

Inputs are continuous artifact-free Flow Rate, validated breath boundaries, breath duration, peak-to-trough flow amplitude, overlapping source respiratory-event intervals, large-leak intervals, and missing-data intervals.

A five-breath window is eligible only when it is continuous and does not overlap missing data, large leak, a signal-artifact interval, a source respiratory event, or the three breaths following a source event. For each eligible window, version 1 calculates the population coefficient of variation for breath duration and amplitude. A window is irregular when `duration_cv >= 0.20` and `amplitude_cv >= 0.30`. At least three consecutive overlapping irregular windows are required to emit a `flagged` likely-wake-breathing candidate spanning their union.

The impact is `caution`, not automatic exclusion. The finding means only that the flow resembles a deliberately conservative irregular-breathing heuristic. It is not confirmed wake, arousal, sleep stage, or a diagnosis. A later metric may choose to exclude these candidates only by explicitly naming this rule and version.

If validated breath boundaries are unavailable, any prerequisite interval is missing/flagged, or fewer than seven eligible consecutive breaths exist, the rule returns `insufficient_evidence` for that scope. Failure to find a candidate is a rule-specific pass only where eligible data were evaluated; it never proves sleep. User-reported awake intervals or future external sleep-stage data remain separate source classes and may validate or contradict the candidate without being overwritten by it.

## Ordering and overlap

Rules run in this dependency order: structural/model integrity, missing coverage and alignment, clock-correction integrity, large leak, signal artifact, then likely wake breathing. Later rules do not run on intervals excluded by a prerequisite. Findings may overlap and are all retained; a higher-priority cause does not erase a lower-priority observation.

Large leak takes precedence over flow morphology because it can reduce measurement reliability. Artifact takes precedence over likely-wake detection. Source respiratory events and their three recovery breaths suppress the likely-wake heuristic so respiratory instability is not relabeled as wake. None of these rules converts an absence of machine events into proof of stable breathing.

## Versioning and reproducibility

Every evaluation stores the rule-set identifier/version, engine version, exact parameters, requested scope, source record identifiers, output findings, and limitations. Changing a threshold, comparison boundary, interval-construction rule, status/impact meaning, dependency, or propagation rule requires a new `pap-pilot.quality` version and new expected fixtures. Version 1 is never silently reinterpreted.

S19 will implement only the structural rules named in its sprint. S20 will implement only the signal rules named in its sprint. Those sprints may discover that the normalized input contract needs a bounded extension, but they may not change this accepted methodology silently; an implementation-blocking ambiguity requires a revised decision or a named follow-up sprint.

## Consequences

- Missing data and unresolved corrections produce explicit uncertainty instead of plausible-looking values.
- Quality remains analysis-specific: a night can contain excluded intervals and still support a narrower calculation, while an unavailable required input forces insufficient evidence.
- Large leak uses the mapped ResMed unintentional-leak semantic and a device-specific threshold without adopting OSCAR summaries as PAP Pilot analysis.
- Artifact and likely-wake findings are conservative companion-derived candidates with visible algorithms and limitations, not clinical labels.
- Short and split sessions remain auditable and visible rather than being silently discarded.
- Experiment sample-size, minimum valid-night duration, metric formulas, outcome thresholds, UI presentation, and AI interpretation remain deferred to their assigned sprints.
