# Decision 0012 — Generic experiment contracts

**Status:** Accepted
**Date:** September 10, 2026
**Decision owner:** Personal prototype
**Contract:** `pap-pilot.generic-experiment` version 1

## Context

The original experiment engine was intentionally built around the retrospective fixed-EPAP ASV PS Min 2-to-1 validation fixture. Its proposal assumes a PAP setting change, its allocation names exactly `baseline` and `intervention`, its classifier selects a fixed metric set, and its prospective entry point invokes safety policy 0009 directly. Those contracts remain valuable regression evidence, but they cannot define experiments in a general PAP analysis product.

PAP Pilot must be able to represent a comparison such as two mask interfaces, sleep routines, equipment states, or other explicitly bounded variables without pretending that each variable is PS Min or that a prospective safety policy has approved it. This sprint does not define new metric algorithms, outcome thresholds, recommendations, or allowed device changes.

## Decision

`pap_pilot.engine.experiments.generic` owns a source-independent generic experiment-definition and descriptive-analysis contract. It imports no OSCAR adapter, API, UI, AI provider, persistence layer, or device-control code. Existing experiment/event schema version 1, storage, baseline/intervention allocation, PS Min classifier, reports, routes, and prospective safety evaluator remain unchanged compatibility contracts.

### Definition

`GenericExperimentDefinition` records the stable experiment link, retrospective or prospective mode, problem, hypothesis, competing explanations, one controlled variable change, named comparison periods, selected metrics, evidence requirements, adverse-effect/stop/reversion statements, sources, provenance, and limitations. A change identifies its kind as a device setting, equipment, behavior, environment, or other variable and accepts finite scalar reference and comparison values without requiring a PAP setting name.

A definition has exactly one reference period and one or more comparison periods. Period identifiers and labels are caller-defined; each period explicitly lists its normalized night records, and one night cannot appear in more than one period. PAP Pilot does not infer membership from a timestamp, observed setting transition, label, or period order in this contract.

Metric selection is explicit and prespecified. Each selection names a metric identifier, label, unit, per-period minimum calculated-night count, and methodology/source records. The generic layer does not assert that an arbitrary identifier has a validated algorithm and does not calculate the selected metric. It accepts a complete metric/night observation ledger in which every entry is either calculated or explicitly insufficient, with source and provenance links.

### Descriptive analysis

`analyze_generic_experiment` reports minimum, median, and maximum calculated values for every selected metric and named period, then reports each comparison-period median minus the reference-period median. Evidence minima are applied independently per selected metric and period. Missing observations and failed minima remain explicit; they produce partial or not-evaluable status rather than zero, imputation, or a fabricated difference.

The generic result assigns no favorable direction, meaningful-change threshold, causal conclusion, clinical classification, next action, or setting recommendation. The fixed PS Min outcome classifier remains a separate version-1 ruleset and is not silently applied to other variables or metrics.

### Safety-policy dispatch

Prospective definitions must name a policy identity and version. `dispatch_generic_experiment_safety` uses a closed registry: the only supported entry remains policy 0009 version 1, and it delegates to the unchanged `evaluate_prospective_safety` implementation only when the generic change exactly matches the typed legacy proposal. Missing policy input, mismatched change data, and unregistered policy identities fail closed.

A retrospective definition has no prospective safety policy. Dispatch returns `not_applicable` with an explicit reason; this state is not eligibility or approval. No non-PS-Min prospective action is authorized by the generic contract.

## Compatibility

The PS Min 2-to-1 proposal, allocation, classifier, append-only store, reports, API/UI compatibility paths, AI gate, and safety-policy tests retain their exact contracts. A PS Min prospective definition can reference policy 0009 and receive the same eligibility and failure vocabulary through the dispatcher. Direct callers of `evaluate_prospective_safety` receive the unchanged result.

## Consequences

- A non-PS-Min retrospective experiment can be represented and analyzed without masquerading as a device-setting change.
- Period names and metric selections no longer come from PS Min-specific enums or classifier constants in the generic path.
- Metric calculation, automatic cohort/period selection, generic append-only persistence, generic API/UI workflow, outcome methodology, recommendations, AI activation, and device interaction remain outside this contract.
- Adding a prospective policy or expanding allowed settings requires a new reviewed policy version and cannot occur by registering arbitrary runtime code.
