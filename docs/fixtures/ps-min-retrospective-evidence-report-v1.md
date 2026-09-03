# PS Min retrospective evidence report v1

**Schema identifier:** `pap-pilot.retrospective-evidence-report`

**Schema version:** 1

**Status:** `not_evaluable_without_fabrication`

**Frozen output:** `tests/fixtures/ps-min-retrospective-evidence-report-v1.json`

## Purpose

This report is the deterministic, structured presentation of the S31 PS Min 2-to-1 reconstruction fixture. It gives later API and interface work one versioned engine result to display without making the interface calculate outcomes or turn absent evidence into plausible values.

## Review contract

The JSON envelope identifies its format and version. The report identifies its schema, record, engine, fixture, experiment, and evaluation versions or records; retains the known setting change, facts, and replay history; and links every claim to a source inventory.

Baseline and intervention sections expose night and quality-report counts. Objective sections cover exactly mean Mask Pressure above EPAP and the minute-ventilation upper-tail ratio. Subjective sections cover awakenings, sleep quality, morning energy, and daytime tiredness. Each outcome retains its prespecified unit, favorable direction, and threshold so that the analytical contract is visible even though no result is available.

Quality, confounder, adverse-effect, and representative-interval sections remain explicit rather than disappearing from the output. The complete missing-input inventory states what is absent and what each absence blocks. Uncertainty and limitation statements bound interpretation.

## Current result

Both periods have zero retained nights. All objective and subjective arm summaries are empty, their calculated values and outcome states are null, and both representative intervals have null bounds. Quality, confounder, and adverse-effect record counts are zero. The classification section is `not_issued`, with null classification and action fields plus the deterministic S31 reason codes.

These values mean that the retained record cannot support a retrospective comparison. They do not mean that the outcomes were zero, unchanged, favorable, adverse-free, or safe.

## Stability and privacy

`pap_pilot.engine.reports.build_ps_min_retrospective_evidence_report` builds an immutable report, and `serialize_retrospective_evidence_report` produces canonical compact JSON or the reviewable indented form used by the snapshot. The snapshot test compares the complete indented output byte for byte and separately verifies canonical serialization and evidence linkage.

The snapshot contains no private OSCAR profile, machine, session, therapy date, signal, metric, journal response, confounder, adverse effect, or representative waveform. It was generated entirely from the non-private S31 repository fixture. No OSCAR database is accessed to build the report.

## Scope boundary

The report is an engine artifact, not a web view or AI-authored interpretation. It does not provide a clinical conclusion, infer causality, recommend a PAP setting, change a device, or persist data. Later work may display the structured fields, but it must preserve their versions, source links, missing states, and null result fields.
