# Decision 0008 — Retrospective evaluation orchestration

**Status:** Accepted
**Date:** September 4, 2026
**Applies to:** S37D and retrospective evaluation schema version 1

## Decision

PAP Pilot will compose the explicitly selected S37A OSCAR cohort with the correction-resolved S37B/S37C experiment replay through one deterministic application workflow. The adapter-to-engine workflow maps only the already extracted schema-17 time-correction evidence; it does not query OSCAR, select sessions, detect a settings change, or infer user intent.

The source-independent engine operation requires exactly one effective accepted proposal and user-confirmed boundary linked to the selected cohort, exactly one retrospective evidence manifest for every selected night, and exact clock-correction evidence for every selected session. It refuses missing, duplicate, outside, stale, or inconsistently linked inputs rather than silently dropping them.

## Quality and timeline roles

The allocation request evaluates all three required signals, Flow Rate/Mask Pressure alignment, and corrected-wall-clock integrity for every selected night. S37A `confirmed_none`, `supported_constant`, and `unsupported_drift` states map explicitly into the existing quality-layer clock contract. Unsupported drift blocks corrected-wall-clock allocation for the affected night; a reproducible constant correction remains a visible caution; normalized signal timestamps remain unchanged.

Both objective metrics retain their accepted raw-relative, metric-specific quality requests. The evaluation bundle materializes those structural reports as well as every full per-session signal-quality report so every quality report and finding identifier cited by allocation, a metric, or classification resolves inside the bundle.

Missing validated breath-detector input remains the existing explicit `wake_prerequisite_missing` finding. It is retained as a limitation but is not passed to period allocation as a universal night exclusion because version-1 pressure and ventilation metrics are PAP-on calculations that explicitly do not establish sleep or require breath boundaries. Each metric continues to apply its own accepted leak and artifact exclusions.

## User evidence and classification

The classifier receives only correction-resolved effective journal entries and the exact journal-reference, confounder, and adverse-effect events linked by the complete S37C per-night manifests. Status-only manifests remain in the bundle even when they create no event, so unavailable, not reported, and none reported do not collapse into one another.

Every selected night receives both version-1 metric evaluations, including nights later excluded from arm aggregation. The existing classifier alone determines clear improvement, probable improvement, mixed tradeoff, no meaningful change, probable worsening, or rules-required inconclusive, and its existing action mapping remains unchanged.

## Output and provenance

Retrospective evaluation schema version 1 is an immutable in-memory bundle containing the selected normalized nights, mapped clock evidence, allocation and metric quality reports, signal-quality reports, allocation, both per-night metrics, retrospective manifests, effective journals and events, and the classification. Its deterministic identity covers all component identities and its source inventories reach every selected night, normalized session and signal record, quality report and finding, metric, effective event, user-evidence manifest, allocation, and classification.

S37D does not persist an evaluation event, build the retrospective report, choose waveform excerpts, change the API or UI, implement prospective behavior, add a metric or threshold, invoke AI, write OSCAR data, or change a PAP device. S37E owns report assembly and selected evidence excerpts; S37F owns API/UI integration.
