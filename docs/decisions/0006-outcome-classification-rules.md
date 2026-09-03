# 0006 — Retrospective outcome classification rules

**Status:** Accepted

**Date:** September 2, 2026

**Rule-set identifier:** `pap-pilot.ps-min-outcome-classification`

**Rule-set version:** 1

## Context

PAP Pilot must classify the retrospective PS Min 2-to-1 experiment from deterministic objective metrics and the version-1 sleep journal. The source experiment is an unblinded, nonrandomized before-and-after observation in one person. Its result can support a transparent within-user engineering conclusion, but it cannot establish clinical benefit or causality.

The [CENT 2015 explanation and elaboration](https://doi.org/10.1136/bmj.h1793) recommends reporting each period's outcomes and, when repeated observations are combined, a summary such as a mean or median with variability. The [FDA's fit-for-purpose clinical outcome assessment guidance](https://www.fda.gov/media/159500/download) treats meaningful within-patient change as something that must be justified for the instrument and context. PAP Pilot's journal is project-specific and neither objective metric has a validated clinical cutoff, so the thresholds below are deliberately prespecified engineering boundaries, not minimal clinically important differences.

## Scope and input evidence

Version 1 applies only to the controlled retrospective fixed-EPAP ASV experiment in which PS Min changed from 2 to 1 cm H₂O. It consumes:

- the effective accepted proposal and its `minimum_valid_nights` value;
- the effective confirmed setting-change event;
- S27 allocations and exclusions for every candidate night;
- per-night results for both metrics in `pap-pilot.ps-min-objective-metrics` version 1;
- effective `pap-pilot.sleep-journal` version-1 entries linked to allocated nights;
- effective confounder and adverse-effect evidence; and
- every relevant source, quality, allocation, metric, journal, and event identifier.

Only S27 nights with status `included` enter an arm. The required valid-night count is `max(3, proposal.minimum_valid_nights)` independently in baseline and intervention. The proposal value is therefore interpreted as a per-arm minimum in rule-set version 1. Excluded nights remain disclosed but never supply an outcome value.

Both objective metrics require at least the valid-night minimum of `calculated` values in each arm. Each subjective outcome is separately evaluable only with at least the valid-night minimum of non-null entries in each arm. At least two of the four subjective outcomes must be evaluable, and one must be either `sleep_quality` or `morning_energy`. No value is imputed, carried between nights, or extracted from free text.

## Period summaries and direction consistency

For every evaluable outcome, calculate the baseline median, intervention median, and delta `intervention_median - baseline_median`. Retain every nightly value and report each arm's minimum, median, maximum, count, and median absolute deviation. The classifier does not treat overlapping nightly observations as independent and does not calculate or interpret a p-value.

A median delta reaches a meaningful boundary only when at least two thirds of intervention-arm values, using exact rational comparison `3 * matching_count >= 2 * intervention_count`, are on the same side of the baseline median as the proposed direction. Equality with the baseline median is neutral and does not count toward direction consistency. A delta reaching a boundary without this consistency is `unstable`, not meaningful.

The outcome directions and inclusive thresholds are:

| Outcome | Favorable state | Neutral state | Adverse state |
|---|---|---|---|
| `mean_mask_pressure_above_epap` | Delta `<= -0.5 cm H₂O`, labeled `expected_mechanism` rather than clinical benefit | Absolute delta `< 0.5 cm H₂O` | Delta `>= +0.5 cm H₂O`, labeled `unexpected_mechanism` |
| `minute_ventilation_upper_tail_ratio` | Delta `<= -0.10` | Absolute delta `< 0.10` | Delta `>= +0.10` |
| `awakenings_count` | Delta `<= -1` awakening | Absolute delta `< 1` awakening | Delta `>= +1` awakening |
| `sleep_quality` | Delta `>= +1` scale point | Absolute delta `< 1` scale point | Delta `<= -1` scale point |
| `morning_energy` | Delta `>= +1` scale point | Absolute delta `< 1` scale point | Delta `<= -1` scale point |
| `daytime_tiredness` | Delta `<= -1` scale point | Absolute delta `< 1` scale point | Delta `>= +1` scale point |

The pressure metric is mechanistic evidence only. Its favorable-direction label means the expected reduction in measured pressure exposure occurred; it cannot by itself make an experiment an improvement. A lower ventilation upper-tail ratio is treated as favorable stability evidence and a higher ratio as adverse evidence only for this within-user rule set; neither state is a diagnosis or clinical normality judgment.

## Subjective-domain aggregation

Among evaluable journal outcomes:

- `favorable` means at least two are favorable and none is adverse;
- `adverse` means at least two are adverse and none is favorable;
- `mixed` means at least one is favorable and at least one is adverse;
- `neutral` means every evaluable outcome is neutral;
- `weak_favorable` means exactly one is favorable and none is adverse;
- `weak_adverse` means exactly one is adverse and none is favorable; and
- `unstable` means any evaluable outcome reaches a median boundary without direction consistency.

Weak and unstable subjective evidence cannot independently support improvement, worsening, or no meaningful change.

## Confounders and adverse effects

For each arm, calculate the fraction of journaled nights with one or more reported confounders. A `confounder_imbalance` exists when the absolute arm-fraction difference is at least one third. If more than one third of journal entries in either arm use `not_reported`, confounder evidence is insufficient. Categories and original details remain visible but are not assigned numerical weights or causal effects.

A confounder imbalance downgrades a would-be `clear_improvement` to `probable_improvement`. Every other would-be directional result with that imbalance becomes `inconclusive`, because version 1 cannot distinguish the setting effect from the coincident context. Insufficient confounder reporting always yields `inconclusive`. Balanced reported confounders are disclosed limitations and do not prove absence of confounding.

Any effective adverse-effect event is an adverse domain. It prevents `clear_improvement`, `probable_improvement`, and `no_meaningful_change`. If another domain is favorable, the result is `mixed_tradeoff`; otherwise it is `probable_worsening`. Severity interpretation and prospective stop rules remain outside this retrospective rule set.

## Six classifications

After all sufficiency gates pass and before the confounder downgrade is applied, derive these domain signals:

- favorable signals: `expected_mechanism`, favorable ventilation, and favorable subjective domain;
- adverse signals: `unexpected_mechanism`, adverse ventilation, adverse subjective domain, and any adverse-effect event.

Apply the following precedence in order:

| Order | Classification | Exact rule |
|---:|---|---|
| 1 | `inconclusive` | Any input/version/linkage/sufficiency gate fails, any required objective outcome is unstable, the subjective domain is unstable, or confounder reporting is insufficient. |
| 2 | `mixed_tradeoff` | At least one favorable signal and at least one adverse signal. |
| 3 | `clear_improvement` | `expected_mechanism`, ventilation favorable or neutral, subjective favorable, no adverse signal or adverse-effect event, and no confounder imbalance. |
| 4 | `probable_improvement` | At least two favorable signals, no adverse signal or adverse-effect event; also the result of applying the defined confounder downgrade to an otherwise clear improvement. |
| 5 | `probable_worsening` | At least two adverse signals and no favorable signal, or an adverse-effect event with no favorable signal. |
| 6 | `no_meaningful_change` | Pressure, ventilation, and the subjective domain are all neutral, with no adverse-effect event. |

Any complete pattern not matching a row is `inconclusive`. In particular, one favorable or adverse signal, weak subjective evidence, or a mechanism change without corroborating outcome evidence is not rounded into a directional classification.

## Next-action rules

The action vocabulary is exactly `keep`, `revert`, `extend`, and `inconclusive`:

| Classification or evidence state | Action | Meaning |
|---|---|---|
| `clear_improvement` or `probable_improvement` | `keep` | The retrospective evidence supports retaining the tested setting, subject to manual review and later safety policy. |
| `probable_worsening` | `revert` | The retrospective evidence supports returning to the documented prior setting, performed manually outside PAP Pilot. |
| `no_meaningful_change` | `revert` | No meaningful benefit supports retaining the experimental setting; this is an analytical next action, not device control. |
| `inconclusive` caused only by too few otherwise valid nights, too few journal responses, or unstable outcomes | `extend` | More observations of the same controlled comparison could resolve the named insufficiency and no adverse-effect event is present. |
| `mixed_tradeoff` | `inconclusive` | Version 1 has no user-preference weights with which to resolve a genuine tradeoff. |
| Any other `inconclusive` state, any confounder imbalance not merely downgrading an otherwise clear result, unsupported versions, broken linkage, or an adverse effect combined with insufficient evidence | `inconclusive` | More of the same data is not deterministically sufficient to choose keep or revert. |

These are evidence-record actions for the retrospective report. They never alter a PAP device, activate a prospective experiment, override an effective stop/revert condition, or replace user/clinician review.

## Boundary examples

| Example | Inputs | Required result |
|---|---|---|
| Pressure threshold equality | Pressure delta `-0.50`, consistent on exactly two of three intervention nights | `expected_mechanism` |
| Pressure just inside neutral | Pressure delta `-0.499999` | neutral |
| Ventilation adverse equality | Ratio delta `+0.10`, consistent on four of six intervention nights | adverse ventilation |
| Rating threshold equality | Sleep-quality delta `+1.0`, consistent on two of three intervention nights | favorable sleep quality |
| Median without consistency | Sleep-quality delta `+1.0`, but only one of three intervention values is above the baseline median | unstable subjective evidence, therefore `inconclusive`; `extend` if this is the only insufficiency |
| Clear improvement | Expected pressure mechanism, neutral ventilation, favorable subjective domain, complete confounder reporting without imbalance, no adverse effect | `clear_improvement` plus `keep` |
| Probable improvement | Expected pressure mechanism and favorable ventilation, subjective domain neutral, no adverse signals or confounder imbalance | `probable_improvement` plus `keep` |
| Mixed tradeoff | Expected pressure mechanism and favorable sleep quality, but adverse ventilation | `mixed_tradeoff` plus `inconclusive` |
| No meaningful change | Pressure, ventilation, and every evaluable subjective outcome neutral | `no_meaningful_change` plus `revert` |
| Probable worsening | Unexpected pressure mechanism and adverse subjective domain, with no favorable signal | `probable_worsening` plus `revert` |
| Too few nights | Two included baseline nights and three intervention nights when the per-arm minimum is three | `inconclusive` plus `extend` if no adverse effect exists |
| Missing objective metric | Adequate nights but fewer than the required calculated ventilation results in either arm | `inconclusive`; `extend` only when additional otherwise compatible nights could supply the result |
| Sparse journal | Only one subjective outcome evaluable, or neither sleep quality nor morning energy evaluable | `inconclusive` plus `extend` if no other blocker or adverse effect exists |
| Confounder uncertainty | More than one third of an arm's journal entries are `not_reported` | `inconclusive` plus `inconclusive` action |

## Reproducibility and exclusions

An implementation must return the rule-set identifier/version, classification, action, per-arm counts and summaries, every outcome state and consistency count, thresholds, confounder fractions/status, adverse-effect identifiers, insufficiency reasons, limitations, and all source evidence identifiers. Changing a threshold, direction, minimum count, summary statistic, consistency fraction, confounder rule, precedence, classification, or action mapping requires a new rule-set version and boundary fixtures.

This decision does not implement the classifier, infer journal fields from prose, add AI judgment, define prospective safety or lifecycle behavior, issue device instructions, choose representative waveforms, or produce UI/report prose. S30 owns deterministic implementation.
