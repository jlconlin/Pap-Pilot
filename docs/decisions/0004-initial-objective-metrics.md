# 0004 — Initial objective metrics for the PS Min experiment

**Status:** Accepted

**Date:** September 2, 2026

**Metric-set identifier:** `pap-pilot.ps-min-objective-metrics`

**Metric-set version:** 1

## Context

The first retrospective experiment compares otherwise unchanged fixed-EPAP ASV therapy before and after PS Min changed from 2 to 1 cm H₂O. PAP Pilot needs the smallest objective metric set that can establish whether delivered pressure exposure changed and whether ventilation became more or less unstable. The metrics must be calculated independently from normalized source waveforms rather than copied from OSCAR or device summaries.

The experiment also includes subjective reports of awakenings, sleep quality, morning energy, and daytime tiredness. Objective metrics do not replace those outcomes, establish causality, or decide whether the change was beneficial. Outcome weighting, meaningful-change thresholds, valid-night rules, minimum baseline/intervention nights, and final classification remain deferred.

## Evidence and rationale

ResMed's [Therapy Handbook](https://document.resmed.com/documents/us/10114280r1_ResMed_Therapy_Handbook_AMER_Eng_Digital_SinglePages.pdf) defines pressure support as IPAP minus EPAP and says the ASV algorithm adjusts pressure support between Min PS and Max PS while monitoring minute ventilation. ResMed's [PaceWave ASV description](https://document.resmed.com/en-us/documents/products/machine/aircurve-series/product-brochure/10111604r2-ASV-practical-brochure-EMEA-EN-LOW.pdf) describes a target based on recent minute ventilation and reduction of pressure support toward the prescribed minimum when ventilation is above target. These device-specific descriptions make pressure exposure and ventilation stability the direct observable consequences of a PS Min change.

Gunn et al., [“Estimation of adaptive ventilation success and failure using polysomnogram and outpatient therapy biomarkers”](https://doi.org/10.1093/sleep/zsy033), reported that persistent ASV pressure cycling could accompany arousals and that upper-tail-to-median ventilation summaries were associated with pressure cycling. Malhotra et al., [“Characterizing respiratory parameters, settings, and adherence in real-world patients using adaptive servo ventilation therapy”](https://doi.org/10.5664/jcsm.9412), found no clinically important aggregate differences in respiratory rate, minute ventilation, leak, or residual AHI across PS Min groups while acknowledging that individuals may respond differently. PAP Pilot therefore performs a within-user comparison, records both objective and subjective evidence, and assigns no favorable direction or clinical threshold in this decision.

The normalized input and quality contracts are defined in `docs/decisions/0002-normalized-core-records.md`, `docs/decisions/0003-initial-quality-flags.md`, and `docs/research/oscar-aircurve-asv-signal-map.md`. Flow Rate and Mask Pressure are synchronized 25 Hz waveforms, Leak is a sparse unintentional-leak trace, gaps remain explicit, and the current quality rule set is `pap-pilot.quality` version 1.

## Decision

Version 1 contains exactly two objective metrics:

| Order | Metric ID | Algorithm version | Result | Purpose |
|---:|---|---:|---|---|
| 1 | `mean_mask_pressure_above_epap` | 1 | cm H₂O | Quantify the time-averaged mask-pressure exposure above the fixed EPAP setting. |
| 2 | `minute_ventilation_upper_tail_ratio` | 1 | unitless ratio | Quantify upper-tail dispersion of independently calculated one-minute inspiratory ventilation. |

The first metric establishes the delivered pressure consequence of the setting change. The second supplies the respiratory-stability counterweight needed to avoid calling lower pressure an improvement when ventilation becomes more variable. Neither metric alone nor their unweighted pair determines the experiment outcome.

No third metric is selected. A third initial metric would either duplicate these questions, promote machine labels with unresolved completeness into an authoritative outcome, or require an independently validated breath detector that does not yet exist. The later sleep journal supplies the subjective outcomes; it is not converted into an objective metric.

## Common metric contract

### Evaluation scope and settings

One result evaluates exactly one normalized `NightRecord` and uses its one or more sessions. Calculating one result per night preserves night-to-night variation for the later experiment comparison rather than collapsing an entire arm into one pooled value. Every included session must have the complete supported fixed-EPAP ASV setting signature: `therapy_mode_code=6`, `loader_mode_code=7`, `epap`, `ps_min`, `ps_max`, and `max_ipap`, with `ps_min <= ps_max` and `epap + ps_max = max_ipap` under the existing normalized setting contract. All sessions in the night must have the same six setting values. Missing, unsupported, or inconsistent settings produce `insufficient_evidence`; values are never carried from another session or night.

A night with multiple compatible sessions may be evaluated, but each session and each source segment remains independent. No waveform, sparse value, eligible run, or rolling window crosses a session or EventList boundary. A night containing different settings remains insufficient; the metric layer neither divides a night nor decides experiment membership.

Both metrics use raw relative time only. An unresolved device-time correction does not block duration, alignment, or within-session calculations because no corrected wall-clock or therapy-date conclusion is made. Raw and corrected timestamps remain separate.

### Sample-cell convention

Each uniform waveform sample at `t_i` represents a left-constant half-open cell `[t_i, t_(i+1))`; the segment's end-exclusive boundary supplies the final cell end. When a cell only partly overlaps an eligible interval, its value is weighted by the exact positive overlap duration. The engine never adds a sample at the segment end, interpolates across a cell or gap, resamples a waveform, smooths values, or bridges EventLists or sessions.

### Required quality and eligible intervals

Each metric declares its own required signals and quality findings below. A `flagged` or `insufficient_evidence` finding with `exclude_interval` removes exactly that half-open interval. A whole-scope missing or unsupported prerequisite blocks only the affected metric. Overlapping exclusions are unioned without double-counting, and the result retains each original finding identifier and reason.

Each calculated result requires at least `minimum_eligible_duration_ms = 300000` across its eligible runs. This five-minute engineering minimum is metric-specific: it is not a universal valid-night rule, adherence threshold, sleep-duration claim, or experiment sample-size rule. Duration may accumulate across compatible sessions and segments, but no calculation bridges their boundaries.

The `short_session` and `split_session_night` findings remain disclosed cautions and do not independently exclude data. The metrics use raw relative time, so `clock_correction_integrity` blocks them only if the normalized signals do not share a common raw basis; the absence of a corrected timeline alone does not block them.

Likely-wake-breathing findings are retained with the metric evidence but are not an exclusion in metric-set version 1. No validated breath detector currently exists, and treating its absence as proof of sleep or silently discarding provisional candidate intervals would both be misleading. Metric results therefore describe eligible PAP-on breathing, not sleep-only breathing, and cannot establish sleep time, awakenings, arousals, or sleep stage. A future sleep-stratified metric requires a separately validated input and a new metric-set version.

Machine-labeled OA, CA, UA, hypopnea, RERA, and Large Leak records do not define or censor either metric. Large Leak contributes through the accepted quality rule, where machine spans remain visibly distinct from threshold-derived leak evidence. Other machine event counts may be displayed later as reference overlays, but their unresolved completeness prevents absence from becoming zero and prevents a derived AHI or event rate from joining this initial metric set.

### Result and provenance

Every metric result is companion-derived and stores at least:

- `metric_set_id` and `metric_set_version`;
- `metric_id` and a metric algorithm version;
- `status`, stable reason code, value, and unit when calculated;
- the exact parameter snapshot, including sample-cell convention, minimum eligible duration, and any rolling-window or quantile parameters;
- the evaluated night identifier, its session identifiers, and their complete setting-record identifiers;
- source signal, segment, and provenance identifiers actually used;
- quality rule-set identifier/version and every consulted quality-finding identifier;
- requested, eligible, and excluded half-open raw-time intervals, with total durations;
- observation or sample-cell counts appropriate to the formula; and
- the metric-specific limitations below.

Repeated evaluation of identical normalized records, quality findings, scope, and metric versions must produce an identical result and stable identifier. OSCAR summaries may be retained separately for cross-checking but are never source identifiers for these calculated values.

### Status and insufficient-evidence behavior

A metric result has status `calculated` or `insufficient_evidence`. Version 1 uses these insufficient-evidence reasons:

| Reason code | Meaning |
|---|---|
| `settings_unavailable` | A required setting is missing or cannot be interpreted under the supported fixed-EPAP ASV contract. |
| `settings_inconsistent` | Sessions in the requested night do not have an identical supported setting signature. |
| `required_signal_unavailable` | A required normalized signal is missing or has no usable data. |
| `unsupported_signal_contract` | A required representation, unit, semantic, timing, or alignment contract is unsupported. |
| `quality_prerequisite_unresolved` | Required quality evidence is unavailable for the whole requested scope. |
| `eligible_duration_below_300000_ms` | Fewer than 300,000 ms remain after required intersections and exclusions. |
| `too_few_ventilation_windows` | Fewer than twenty complete one-minute ventilation observations remain for the ventilation ratio. |
| `nonpositive_ventilation_median` | The ventilation ratio's median denominator is not finite and strictly positive. |

Insufficient evidence for one metric does not erase a calculated value or observed quality finding for the other. A result never substitutes zero, a machine/OSCAR summary, an adjacent session, or an excluded interval for missing evidence.

## Metric 1 — `mean_mask_pressure_above_epap`

### Purpose and inputs

This metric estimates the time-averaged measured mask-pressure exposure above the session's fixed EPAP setting. It requires:

- complete supported fixed-EPAP ASV settings;
- `flow_rate` as a uniform 40 ms waveform in L/min;
- `mask_pressure` as a uniform 40 ms waveform in cm H₂O;
- `leak_rate` as sparse timed updates in L/min with `unintentional` semantics;
- exact Flow Rate/Mask Pressure alignment; and
- version-1 missing-signal, alignment, large-leak, and signal-artifact findings for the requested scope.

Flow Rate is required even though it does not appear numerically in the formula because the metric is intended to describe pressure delivered during synchronously observed breathing, not an unpaired pressure trace.

### Eligible interval

Start with the intersection of Flow Rate, Mask Pressure, and Leak evidence coverage. Exclude every interval affected by Flow Rate or Mask Pressure missing coverage, Flow Rate/Mask Pressure misalignment, threshold-derived or machine-labeled Large Leak, unresolved leak evidence, and Flow Rate or Mask Pressure digital-clipping, isolated-impulse, or artifact-input findings. A required whole-scope insufficiency blocks the metric.

### Formula

For each eligible Mask Pressure sample cell `i`, let `P_i` be its value in cm H₂O, let `E` be the session's fixed EPAP setting in cm H₂O, and let `d_i` be the cell's eligible overlap duration in milliseconds. Define positive mask-pressure excursion as:

```text
X_i = max(P_i - E, 0)
```

The metric is the duration-weighted mean:

```text
mean_mask_pressure_above_epap = sum(X_i * d_i) / sum(d_i)
```

The result unit is cm H₂O. The denominator is the exact eligible duration and must be at least 300,000 ms. Cells from different eligible runs may contribute to the same sum, but no cell spans an excluded interval, segment boundary, or session boundary.

### Interpretation and limitations

A smaller value means that measured mask pressure spent less average amplitude above the fixed EPAP setting during eligible PAP-on time. It does not by itself mean better therapy, adequate ventilation, less work of breathing, improved comfort, or fewer arousals.

The value is not the device's commanded pressure support, a substitute for IPAP or EPAP settings, or a patient-effort measurement. Mask Pressure is a measured waveform affected by the device waveform, mask/circuit dynamics, and source accuracy. Clamping values below EPAP prevents negative deviations from cancelling positive exposure but does not relabel those deviations. Comparisons are intended only within the same user, device/mask context, supported mode, and otherwise controlled experiment.

## Metric 2 — `minute_ventilation_upper_tail_ratio`

### Purpose and inputs

This metric estimates how far the upper tail of independently calculated inspiratory minute ventilation lies above its typical value. It requires:

- complete supported fixed-EPAP ASV settings;
- `flow_rate` as a uniform 40 ms waveform in L/min using the established positive-inspiration sign convention;
- `leak_rate` as sparse timed updates in L/min with `unintentional` semantics; and
- version-1 missing-signal, large-leak, and Flow Rate artifact findings for the requested scope.

Mask Pressure is not a numerical input. Keeping the physiological response metric independent from the pressure waveform allows a pressure-quality problem to make metric 1 insufficient without automatically destroying otherwise usable flow evidence for metric 2.

### Eligible interval and one-minute observations

Start with the intersection of Flow Rate and Leak evidence coverage. Exclude every interval affected by Flow Rate missing coverage, threshold-derived or machine-labeled Large Leak, unresolved leak evidence, and Flow Rate digital-clipping, isolated-impulse, or artifact-input findings. A required whole-scope insufficiency blocks the metric.

Divide the remaining evidence into maximal continuous eligible runs without crossing a source segment or session. In every run at least 60,000 ms long, create observation anchors at `run_start + 60000 ms` and every 1,000 ms thereafter through `run_end`. The observation at anchor `t` uses the half-open window `[t - 60000, t)`. A window is admitted only when every millisecond is eligible Flow Rate and Leak evidence within the same run.

For each admitted window, sum the positive Flow Rate sample cells with exact duration weighting:

```text
MV_60(t) = sum(max(F_i, 0) * d_i) / 60000
```

Here `F_i` is L/min and `d_i` is milliseconds within the one-minute window. Because the window is exactly one minute, the result is inspiratory liters per minute. At least twenty complete observations and 300,000 ms of total eligible source duration are required.

### Quantile and metric formula

Sort the `n` complete observations in ascending order as `x_1 ... x_n`. Quantiles use the Hyndman-Fan type-7 linear rule: for probability `p`, calculate `h = 1 + (n - 1) * p`, `j = floor(h)`, and `g = h - j`; then `Q_p = x_j + g * (x_(j+1) - x_j)`, with the upper endpoint used when `j = n`.

The metric is:

```text
minute_ventilation_upper_tail_ratio = Q_0.95(MV_60) / Q_0.50(MV_60)
```

The result is unitless. The median denominator must be finite and strictly positive. The exact Q50 and Q95 values are retained as supporting measurements in L/min.

### Interpretation and limitations

A value of 1 means the observed 95th percentile equals the median; larger values indicate more upper-tail dispersion in one-minute inspiratory ventilation. No value in metric-set version 1 is labeled normal, abnormal, improved, worsened, clinically meaningful, or safe. Outcome-direction and comparison thresholds remain for the later classification decision.

This is an engineering estimate from positive Flow Rate, not the device's proprietary target minute ventilation, alveolar ventilation, spirometry, or a clinical measurement. It does not correct for dead space, body size, mask/circuit dynamics, undetected wake, unrecognized source error, or expiratory volume. The one-minute overlapping windows are intentionally time-localized and highly correlated; their count is evidence density, not an independent sample size for statistical inference. The ratio describes upper-tail dispersion but does not establish periodic breathing, hypocapnia, hyperventilation, an apnea type, or causation by PS Min.

## Explicitly excluded initial metrics

- Machine AHI, event rate, and event-free time are not initial metrics because event-row completeness is unresolved and absence cannot establish zero. Machine-labeled events remain reference evidence with their original provenance.
- OSCAR/device respiratory rate, tidal volume, minute ventilation, target ventilation, Ti, Te, flow-limitation, and pressure summaries are not adopted as PAP Pilot outcomes. They may later cross-check an independently calculated result but cannot silently replace it.
- Breath-morphology, tidal-volume, respiratory-rate, synchrony, and per-breath pressure-support metrics are deferred because the repository has no independently specified and validated breath detector. S20's `ValidatedBreathSeries` is an input contract, not a detector implementation.
- Likely-wake-breathing burden is not promoted from a provisional quality caution to an experiment outcome. Subjective awakenings remain user-reported evidence, and PAP-only flow cannot establish sleep stage.
- Leak burden and artifact burden remain quality evidence rather than outcome metrics in this experiment. Improving a quality flag is useful context but does not answer the PS Min hypothesis by itself.

## Reproducibility and change control

Implementations must use fixed synthetic fixtures with hand-calculated eligible intervals, duration weights, one-minute observations, quantiles, and final results. Boundary tests must cover exactly 300,000 ms of eligible duration, one millisecond below it, exactly twenty ventilation observations, nineteen observations, segment/session gaps, partially excluded sample cells, large-leak and artifact overlap, missing likely-wake prerequisites, and a split night with identical versus inconsistent settings.

Changing a formula, sign convention, sample-cell rule, input requirement, exclusion, window length/step, quantile method, minimum duration/observation count, status/reason meaning, or limitation requires a new metric-set version and new expected fixtures. The accepted version-1 decision is not silently reinterpreted.

## Consequences

- S22 implements only `mean_mask_pressure_above_epap`.
- S23 implements only `minute_ventilation_upper_tail_ratio`.
- S24 is unnecessary because version 1 deliberately selects two metrics.
- Machine/OSCAR summaries remain comparison inputs, not PAP Pilot's analysis.
- The two metrics can be calculated without inventing breath boundaries; missing likely-wake prerequisites remain visible limitations rather than being converted into sleep evidence.
- Later experiment allocation, subjective outcomes, outcome weighting, meaningful-change thresholds, classifications, reports, persistence, UI, and AI remain unchanged and deferred to their assigned sprints.
