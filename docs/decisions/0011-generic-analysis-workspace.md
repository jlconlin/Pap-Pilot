# Decision 0011 — Generic analysis workspace

**Status:** Accepted
**Date:** September 8, 2026
**Decision owner:** Personal prototype
**Contract:** `pap-pilot.analysis-workspace` version 1

## Context

The completed prototype used the PS Min 2-to-1 retrospective experiment as its product-level API and interface root. That slice proved the read-only adapter, deterministic metrics, evidence linkage, append-only experiment history, and safety boundaries, but it made a single settings experiment appear to be the product. The user corrected the intended scope: PAP Pilot is a broader general PAP analysis tool, with experiments as one optional workflow. AirwayLab's recent-night, longitudinal, and night-detail analysis shape is a product reference, not a source-code or algorithm dependency.

## Decision

The generic analysis workspace is the product-level deterministic contract. A workspace contains zero or more therapy-night summaries, longitudinal trend series, evidence records, logical resources, and optional experiment references. It can represent useful analysis without an experiment and without any PS Min setting, metric, label, or route.

The source-independent implementation lives in `pap_pilot.engine.analysis`. It imports no OSCAR adapter, API, UI, AI, persistence, or device code. It defines immutable version-1 records and deterministic JSON serialization but performs no extraction, metric calculation, automatic cohort selection, clinical interpretation, or presentation.

### Analysis unit

`AnalysisWorkspace` is the root record. `AnalysisNight` links a generic normalized therapy night to its sessions, settings, events, signals, quality reports, metric results, journal entries, and evidence. `AnalysisTrend` holds an externally defined metric series and explicit per-night points. `AnalysisEvidence` links settings, events, signals, quality, metrics, journals, or experiment reports without reclassifying their provenance. `AnalysisExperimentReference` is optional and cannot become the workspace root.

### Availability and missing evidence

Availability uses the closed vocabulary `available`, `partial`, `unavailable`, and `not_evaluable`. An available value requires attributable sources. A missing or not-evaluable value requires a stable reason code and cannot carry an invented value. Trend availability must agree with the availability of its points. The workspace source/provenance inventories must include every nested source and provenance identifier.

### Logical resource identity

Transport-independent logical resources use these stable identities:

| Resource | Logical identity |
|---|---|
| Overview | `analysis:overview` |
| Night collection | `analysis:nights` |
| Night detail | `analysis:night:<night-record-id>` |
| Trend collection | `analysis:trends` |
| Trend detail | `analysis:trend:<trend-record-id>` |
| Evidence detail | `analysis:evidence:<evidence-record-id>` |
| Experiment detail | `analysis:experiment:<experiment-record-id>` |

S50 owns HTTP composition and may map these resources to `/api/v1/analysis/overview`, `/api/v1/analysis/nights`, `/api/v1/analysis/nights/{night_record_id}`, `/api/v1/analysis/trends`, `/api/v1/analysis/trends/{trend_record_id}`, `/api/v1/analysis/evidence/{evidence_record_id}`, and `/api/v1/analysis/experiments/{experiment_record_id}`. S49 does not add those routes.

### PS Min compatibility

The existing PS Min 2-to-1 fixture, report, API routes, tests, and safety policy remain unchanged regression evidence. A generic workspace may link that fixture through an optional experiment reference carrying `compatibility_fixture_id`, its experiment and report identifiers, provenance, availability, and limitations. No generic workspace field requires PS Min, and the legacy PS Min summary is not the generic overview.

## Consequences

- S50 can compose general read-only resources from normalized records without redesigning their identity.
- S51 can replace the experiment-first landing page while retaining the old report as a compatibility view.
- New metrics remain separate versioned methodology decisions; this contract does not validate or introduce any analysis algorithm.
- Automatic cohort discovery, night selection, waveform selection, AI interpretation, device interaction, and OSCAR writes remain outside this decision.
- Existing experiment safety constraints remain in force and are not generalized or weakened by the broader analysis workspace.
