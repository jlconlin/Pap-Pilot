# PS Min retrospective fixture v1

**Fixture identifier:** `pap-pilot.ps-min-retrospective`

**Fixture version:** 1

**Status:** Retained facts are replayable; an outcome classification is not yet issuable without fabricating evidence

**Source kind:** Governing-plan facts and explicit missing-input inventory; no private or synthetic therapy observations

## Purpose

This fixture reconstructs everything the repository can currently establish about the informal fixed-EPAP ASV PS Min 2-to-1 experiment and nothing more. It exists to keep the retrospective vertical slice honest: a missing date, night, metric, journal response, confounder, adverse effect, or waveform interval remains missing instead of receiving a plausible placeholder.

`pap_pilot.engine.experiments.reconstruct_ps_min_experiment_fixture` returns an immutable version-1 bundle. Its experiment identity plus problem and hypothesis events replay through the append-only `ExperimentStore`. Those events contain no historical therapy timestamp; zero and the two low event sequence timestamps are documented deterministic repository-fixture sentinels.

## Retained facts

- The governing plan identifies an informal fixed-EPAP ASV change from PS Min 2 to PS Min 1 cm H₂O.
- The accepted deterministic contract uses objective metric set `pap-pilot.ps-min-objective-metrics` version 1 and outcome-classification rule set `pap-pilot.ps-min-outcome-classification` version 1.
- The plan says the earlier informal interpretation was subjectively meaningful, but it contains no attributable per-night version-1 journal responses. That statement remains planning context and is not converted into awakenings, ratings, confounders, or adverse effects.

## Explicit missing inputs

- The exact accepted proposal, including baseline dates, complete setting context, invalid-night criteria, and evidence links.
- The user-confirmed application timestamp for the intended sustained PS Min change.
- The exact normalized baseline and intervention cohort.
- Structural and signal-quality reports for that cohort.
- Both version-1 objective metric results for every included night.
- Attributable per-night awakenings, sleep-quality, morning-energy, and daytime-tiredness responses.
- Linked confounder and adverse-effect evidence; absence is unknown and does not mean none reported.
- Representative baseline and intervention waveform intervals.

## Deterministic result

The bundle returns `not_evaluable_without_fabrication` and the complete missing-input reason set. Its `allocation` and `outcome_classification` are null, and its normalized nights, quality reports, metrics, journal entries, and observation events are empty. This is deliberately not an `OutcomeClassificationResult`: inventing just enough dates or nights to invoke the classifier would create false evidence and misleading provenance.

The same reconstruction produces the same immutable records and evaluation identifier, and the retained partial history replays identically after the local SQLite experiment store is closed and reopened. When genuine source records become available, they must be added through the existing normalized-data, quality, allocation, metric, journal, event, and classification contracts rather than silently inserted into fixture version 1.

## Privacy boundary

The fixture contains no OSCAR profile or machine identifier, therapy date, session identifier, setting envelope other than the already-governing PS Min 2-to-1 fact, signal sample, event count, calculated health metric, journal value, free-text report, confounder, or adverse-effect observation. Private OSCAR data and local PAP Pilot databases remain ignored and outside version control.

## Scope boundary

This sprint does not produce polished report presentation, a web interface, AI interpretation, a prospective recommendation, lifecycle or safety-policy behavior, or an evaluation event. S32 may report this deterministic insufficiency transparently; it must not replace missing inputs with authored prose or inferred clinical conclusions.
