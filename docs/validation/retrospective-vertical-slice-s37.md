# S37 retrospective vertical-slice validation

**Date:** September 3, 2026
**Scope:** Validate the existing PS Min 2-to-1 retrospective path from disposable OSCAR input through the local UI without adding analytical behavior, prospective workflow, AI, or OSCAR writes.
**Decision:** S37 passes its alternate completion branch because Milestones 1 and 2 pass and every gap preventing Milestones 3 and 4 is assigned to a bounded queued sprint. This document does not claim that the retrospective vertical slice itself is complete.

## Safety and data boundary

The run used only the repository's wholly synthetic schema-17 OSCAR fixture and a temporary local application database. The source SQLite bytes were compared before and after guarded extraction and were identical. No live or private OSCAR database, therapy date, profile, device identifier, waveform, journal response, or application database was accessed or retained. Both temporary databases and the unretained audit harness were removed after validation.

## Evidence exercised

The disposable source was passed through `extract_session_summary`, `extract_session_events`, `extract_flow_rate_signal`, `extract_mask_pressure_signal`, `extract_leak_signal`, and `normalize_oscar_session`. The normalized result contained one night, one session, and the three required signal kinds: `flow_rate`, `mask_pressure`, and `leak_rate`.

The normalized night was passed independently through the structural-quality evaluator, signal-quality evaluator, and both version-1 PAP Pilot metrics. Five structural findings and one signal-quality report were produced. Both metrics correctly returned `insufficient_evidence` because the deliberately tiny waveform excerpts do not satisfy their minimum evidence contracts; neither metric substituted an OSCAR/device summary or fabricated samples.

The current report builder, API, history store, and JavaScript renderer were then exercised. The report returned `not_evaluable_without_fabrication`, listed all eight retained missing-input categories, and contained no source link to the normalized night produced earlier in the same audit. The history contained only the retained problem and hypothesis events, with no accepted proposal or confirmed application boundary. The renderer showed the non-fabrication state and drew no waveform SVG.

The installed `pap-pilot-api` command was also started from a temporary working directory. It bound to `127.0.0.1:8765`; the health, overview, summary, and history requests succeeded over the real loopback socket; and the local store was created as `pap_pilot.sqlite3` in that temporary directory. The served report again had eight missing inputs and no confirmed boundary. The server shut down cleanly.

## Vertical-slice audit

| Plan step | Existing evidence | Result | Bounded next work |
|---|---|---|---|
| 1. Read relevant nights and settings | A guarded adapter reproducibly reads one explicitly identified session, and the S37 disposable run normalized that session. There is no bounded selection/extraction path for candidate sessions spanning the retrospective change or for multi-session nights. | Incomplete | S37A |
| 2. Detect or confirm the settings-change boundary | Boundary allocation and correction contracts exist, but the retained experiment has no accepted proposal or user-confirmed applied timestamp. An observed OSCAR transition is correctly not treated as confirmation. | Incomplete | S37B |
| 3. Assign nights to periods | The allocator is tested in isolation, but no selected retrospective cohort and confirmed boundary are supplied to it. | Incomplete | S37D, after S37A–S37B |
| 4. Apply quality criteria | Structural and signal-quality rules run on a normalized night, but no orchestration applies them across a selected retrospective cohort. | Incomplete | S37D, after S37A |
| 5. Calculate objective outcomes | Both independent metrics run and fail safely on inadequate synthetic evidence, but no linked baseline/intervention metric set exists. | Incomplete | S37D, after S37A–S37B |
| 6. Incorporate journal and confounders where available | The append-only journal schema and store exist. The historical fixture has no attributable entries, and the absence is correctly not interpreted as a negative response. There is no bounded retrospective intake/import path for user-supplied historical evidence or explicit unavailable states. | Incomplete | S37C |
| 7. Show representative waveform segments | The UI can render supplied bounded excerpts and safely displays the current missing state. No attributable baseline/intervention intervals have been selected from the retrospective cohort. | Incomplete | S37E |
| 8. Produce an evidence-linked evaluation | The current report is a stable missing-evidence inventory constructed only from the immutable S31 fixture. It cannot consume a completed evaluation bundle. | Incomplete | S37E, after S37D |
| 9. Determine classification and action | The classifier is exhaustively tested in isolation, but the retained experiment never reaches it because the proposal, boundary, cohorts, and reports are absent. | Incomplete | S37D |
| 10. Display the complete experiment in the UI | The local UI accurately displays the incomplete fixed report and append-only history. Its summary endpoint is frozen at application creation from the S31/S32 fixture and is not built from OSCAR extraction or workspace evaluation. | Incomplete | S37F |

## Milestone decisions

### Milestone 1 — pass

S14C previously accepted the gate after cross-checking the required settings, session, events, Flow Rate, Mask Pressure, and Leak against OSCAR on a protected private copy. The S37 synthetic run reconfirmed deterministic guarded extraction and byte-for-byte source preservation. The evidence supports reproducible extraction without modifying OSCAR data.

### Milestone 2 — pass

The fixed synthetic reference-night expectation, canonical normalized serialization, and versioned structural/signal quality rules remain covered by the existing suite. The S37 run produced the expected normalized signal inventory and executed the quality layer from that mapped record. Together with the accepted S14 cross-check, this satisfies the reference-value and timestamp agreement gate.

### Milestone 3 — not yet passed

The engine components exist, but the current product has no orchestration that turns a selected retrospective OSCAR cohort plus confirmed experiment history and available user evidence into one reproducible, evidence-linked outcome classification. The S37 run proved this directly: the normalized night was absent from the served report's provenance and the fixed fixture remained not evaluable.

### Milestone 4 — not yet passed

The packaged localhost UI and append-only local store work, and their missing-evidence behavior is honest. The PS Min experiment cannot yet be reviewed from beginning to end because the UI receives a fixed incomplete report rather than the result of the extracted retrospective analysis, has no populated periods or metrics, has no selected waveform evidence, and has no issued classification or action.

## Completion evidence

The focused validation command is:

```text
PYTHONPATH=src .venv/bin/python -B -W error::ResourceWarning -m unittest tests.test_session_summary tests.test_structural_quality tests.test_signal_quality tests.test_pressure_metric tests.test_ventilation_metric tests.test_experiment_allocation tests.test_sleep_journal tests.test_outcome_classification tests.test_ps_min_retrospective_fixture tests.test_retrospective_evidence_report tests.test_local_api tests.test_overview_ui tests.test_boundary_corrections -q
```

The complete source-tree validation command is:

```text
PYTHONPATH=src .venv/bin/python -B -W error::ResourceWarning -m unittest discover -s tests -q
```

The bounded queued work is S37A through S37F. Prospective safety work remains after those retrospective gaps; S38 was not started.
