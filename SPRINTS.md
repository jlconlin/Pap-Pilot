# PAP Pilot — short sprint queue

**Governing plan:** `Plan.md`
**Sprint size:** one narrow, independently verifiable development session  
**Rule:** activate and complete only one sprint at a time; commit its changes before stopping

## How to run a sprint

Start a new Codex goal with:

```text
/goal Complete sprint SXX from SPRINTS.md. Read AGENTS.md, Plan.md,
and STATUS.md first. Stay within the sprint's
scope and exclusions. Run its completion check, update SPRINTS.md and
STATUS.md, commit the completed sprint, verify the working tree is clean,
and stop without starting the next sprint.
```

If a sprint uncovers substantial extra work, add a new queued sprint rather than enlarging the active one.

## 0 — Project continuity

### S00 — Create resumable sprint tracking — done

- Objective: Establish the sprint queue, repository instructions, and session handoff record.
- Excludes: Application implementation and OSCAR-data inspection.
- Done when: `AGENTS.md`, `SPRINTS.md`, and `STATUS.md` agree on the next sprint and contain no broken local file references.

### S01 — Select the working name and identifiers — done

- Objective: Select the working product name, technical slug, Python package name, and local database filename, and record the rationale.
- Excludes: Trademark opinions, legal clearance, domains, app-store availability, social handles, logos, and final visual branding.
- Done when: The user explicitly approves one working name and its identifiers, the decision is recorded, and the governing/tracking documents consistently use them.

### S02 — Initialize version-control checkpoints — done

- Objective: Initialize a local Git repository, add a project-appropriate ignore file, and create the first planning checkpoint.
- Excludes: Remote hosting, application implementation, and rewriting the planning documents.
- Done when: The working tree is clean after a commit containing the existing plans and tracking files, and no sensitive/local data is tracked.

## 1 — OSCAR read feasibility

### S03 — Record OSCAR source-material provenance — done

- Objective: Locate the OSCAR 2 SQL Notes and official Python demonstration and record their exact source, version, and retrieval date.
- Excludes: Database access, schema reverse engineering, and adapter code.
- Done when: A short research note identifies both artifacts or precisely documents what remains unavailable.

### S04 — Inventory the local OSCAR database — done

- Objective: Locate the active OSCAR database, record OSCAR/schema versions, and document a safe backup/disposable-copy procedure.
- Excludes: Reading therapy rows or running the demonstration against the live database.
- Done when: Paths and versions are documented without exposing sensitive data, and a protected test-copy procedure is verified.

### S05 — Run the official demonstration — done

- Objective: Run the official OSCAR Python demonstration against only the disposable database copy and capture a sanitized result.
- Excludes: Modifying the demonstration or designing the companion adapter.
- Done when: The command, environment, result, and any failure are reproducibly documented.

### S06 — Map identity and session tables — done

- Objective: Document only the schema fields needed for profiles, machines, sessions, time corrections, and schema identification.
- Excludes: Settings, events, waveforms, and broad schema documentation.
- Done when: Each required internal identity/session value maps to a source field, unit, and caveat.

### S07 — Map settings and events — done

- Objective: Document only the AirCurve 10 ASV settings and event fields needed by the first experiment.
- Excludes: Signals/waveforms and unused device modes.
- Done when: Required settings/events have source fields, encodings, units, and missing-data behavior.

### S08 — Map required signals — done

- Objective: Document the minimum signal/waveform fields needed for the PS Min retrospective experiment.
- Excludes: Signals not tied to an initial metric or evidence view.
- Done when: Each selected signal has source location, units, sample timing, encoding, and quality caveats.

### S09 — Scaffold the Python project — done

- Objective: Create the smallest installable/testable Python project structure for adapter and engine work.
- Excludes: Web UI, AI dependencies, and database extraction logic.
- Done when: The package imports and one smoke test passes using the documented development command.

### S10 — Implement guarded read-only connection — done

- Objective: Open a disposable OSCAR database explicitly read-only and reject missing or unsupported schema versions.
- Excludes: Therapy-data extraction and live-database testing.
- Done when: Tests prove reads succeed, writes fail, and unsupported schemas fail safely.

### S11 — Extract one session summary — done

- Objective: Extract machine/profile provenance, session boundaries, and settings for one selected night.
- Excludes: Events, waveforms, metrics, and multiple-night queries.
- Done when: A deterministic test or sanitized artifact shows the selected session summary with provenance.

### S12 — Extract events for one night — done

- Objective: Add the minimum event extraction needed for the selected reference night.
- Excludes: Waveforms, derived metrics, and broad event coverage.
- Done when: Event types, times, counts, and units can be reproduced for that night.

### S13 — Extract one required signal — done

- Objective: Add extraction for one signal selected in S08, including timestamps and units.
- Excludes: Other signals and derived calculations.
- Done when: A focused test verifies sample count, time range, units, and stable output.

### S14 — Cross-check the reference night — done

- Objective: Compare S11–S13 outputs with OSCAR for one night and record discrepancies.
- Excludes: Fixing unrelated discrepancies or adding more nights.
- Done when: Settings, boundaries, event counts, and the first signal have explicit pass/fail comparisons.

### S14A — Extract Mask Pressure — done

- Objective: Add schema-17 extraction for the required `MaskPressureHi` signal, including timestamps, units, segment boundaries, and provenance.
- Excludes: Leak extraction, derived calculations, signal alignment analysis, and additional nights.
- Done when: Focused tests verify sample count, time range, 25 Hz timing, cm H₂O units, gaps, storage integrity, and deterministic output for `MaskPressureHi`.

### S14B — Extract Leak — done

- Objective: Add schema-17 extraction for the required sparse `Leak` signal, including stored timestamps, units, gaps, and provenance.
- Excludes: Mask Pressure changes, leak-threshold rules, quality classification, derived calculations, and additional nights.
- Done when: Focused tests verify sparse timestamp decoding, values, L/min units, gaps, storage integrity, missing-data behavior, and deterministic output for `Leak` without assuming total-versus-excess semantics.

### S14C — Cross-check remaining signals and accept Milestone 1 — done

- Objective: Cross-check `MaskPressureHi` and `Leak` for the same private reference night against OSCAR and record the Milestone 1 gate decision.
- Excludes: Fixing unrelated discrepancies, adding nights, defining quality rules, normalized records, and derived metrics.
- Done when: Timing, values, units, display behavior, and Leak semantics have explicit pass/fail comparisons; all Milestone 1 exit-criterion evidence is reviewed; and the gate is recorded as accepted or the sprint is blocked by a named discrepancy.

## 2 — Normalized model and fixtures

### S15 — Define normalized core records — done

- Objective: Define versioned records for nights, sessions, settings, events, signals, and provenance.
- Excludes: Quality rules, experiments, persistence, UI, and AI.
- Done when: Records serialize deterministically and required provenance survives a round trip.

### S16 — Map adapter output into normalized records — done

- Objective: Convert the reference-night adapter output into the S15 records.
- Excludes: New OSCAR queries and derived metrics.
- Done when: A test produces stable normalized output from the disposable reference input.

### S17 — Freeze the first reference fixture — done

- Objective: Create a de-identified/fixed reference-night fixture with expected outputs and documented origin.
- Excludes: Additional nights and metric expectations.
- Done when: The fixture is safe to retain, versioned, and detects an intentional mapping change.

### S18 — Define initial quality flags — done

- Objective: Record versioned rules for missing samples, short/split sessions, large leak, artifacts, clock corrections, and likely wake breathing.
- Excludes: Implementing every rule and deciding experiment sample-size thresholds.
- Done when: A methodology decision record defines inputs, outputs, and `insufficient evidence` behavior.

### S19 — Implement structural quality flags — done

- Objective: Implement only missing-data, short-session, split-session, and clock-correction flags.
- Excludes: Leak, artifact, and wake-breathing detection.
- Done when: Focused tests cover passing, failing, and boundary cases for each structural flag.

### S20 — Implement signal quality flags — done

- Objective: Implement only the initially defined leak, artifact, and likely-wake flags.
- Excludes: Experiment classification and UI display.
- Done when: Fixed fixtures exercise each flag and produce versioned quality results.

## 3 — Retrospective experiment engine

### S21 — Choose the initial objective metrics — done

- Objective: Select the smallest metrics needed for the PS Min experiment and define formulas, units, exclusions, and limitations.
- Excludes: Metric implementation and outcome weighting.
- Done when: A methodology decision record names and fully defines each initial metric.

### S22 — Implement initial metric 1 — done

- Objective: Implement and test only the first metric selected in S21.
- Excludes: Other metrics, scoring, and classification.
- Done when: Unit and fixture tests match hand-checked expected values and retain provenance.

### S23 — Implement initial metric 2 — done

- Objective: Implement and test only the second metric selected in S21, or mark this sprint unnecessary if S21 selects one metric.
- Excludes: Other metrics, scoring, and classification.
- Done when: Unit and fixture tests match hand-checked expected values and retain provenance.

### S24 — Implement initial metric 3 — done

- Objective: Closed as unnecessary because S21 selected exactly two initial metrics.
- Excludes: Other metrics, scoring, and classification.
- Done when: The accepted S21 methodology selects fewer than three metrics and records why no third metric belongs in the initial set.

### S25 — Define experiment and event schemas — done

- Objective: Define versioned experiment records and the minimum append-only event types from the governing plan.
- Excludes: Persistence implementation and prospective safety rules.
- Done when: Tests cover valid creation, correction-by-reference, and rejection of destructive replacement.

### S26 — Implement the append-only experiment store — done

- Objective: Persist and replay S25 events in a local SQLite store.
- Excludes: OSCAR writes, UI, synchronization, and event editing/deletion.
- Done when: Replay reconstructs state, corrections preserve history, and destructive mutation is unavailable.

### S27 — Allocate baseline and intervention nights — done

- Objective: Assign nights around a confirmed settings-change boundary and apply existing quality exclusions.
- Excludes: Automatic change detection, metrics, and final classification.
- Done when: Boundary and exclusion tests reproduce expected period membership.

### S28 — Define sleep-journal outcomes and confounders — done

- Objective: Represent the structured sleep-journal responses, optional original free-text notes, and confounders needed by the retrospective fixture.
- Excludes: Forms/UI, automated interpretation of free text, and prospective daily reminders.
- Done when: Structured responses and original notes are append-only, timestamped, attributable, linked to the relevant therapy night, and replay correctly.

### S29 — Define outcome classification rules — done

- Objective: Define thresholds and evidence rules for the six classifications plus keep/revert/extend/inconclusive actions.
- Excludes: AI judgment and implementation.
- Done when: A methodology decision record includes boundary examples and `insufficient evidence` cases.

### S30 — Implement outcome classification — done

- Objective: Implement the deterministic S29 rules using normalized metrics, quality, and reports.
- Excludes: UI and AI-generated interpretation.
- Done when: Table-driven tests cover every classification, action, and insufficient-evidence path.

### S31 — Reconstruct the PS Min experiment fixture — done

- Objective: Assemble the known PS Min 2-to-1 baseline, intervention, reports, and confounders as a replayable experiment.
- Excludes: Polished presentation and prospective recommendations.
- Done when: The fixture evaluates reproducibly with linked evidence and documented missing inputs.

### S32 — Produce the retrospective evidence report — done

- Objective: Generate a deterministic structured report for S31 with metrics, uncertainty, limitations, and representative intervals.
- Excludes: Web UI and AI-written prose.
- Done when: A snapshot test proves stable, traceable output and the result is manually reviewable.

## 4 — Local web interface

### S33 — Add the local API shell — done

- Objective: Expose a health endpoint and read-only experiment-summary endpoint bound to localhost.
- Excludes: Browser UI, mutation endpoints, authentication, and deployment.
- Done when: API tests pass and configuration cannot bind publicly by default.

### S34 — Add the experiment overview page — done

- Objective: Display S32 status, periods, settings, metrics, reports, classification, and limitations.
- Excludes: Waveform rendering and editing.
- Done when: The PS Min overview renders from the API and has a focused UI test or captured verification.

### S35 — Add representative waveform display — done

- Objective: Display the preselected baseline/intervention waveform intervals with units and evidence links.
- Excludes: Arbitrary signal exploration and automatic interval selection.
- Done when: Both periods render correctly and missing signals fail visibly and safely.

### S36 — Add append-only notes and corrections — done

- Objective: Allow a boundary correction and note to be added as new events without erasing history.
- Excludes: General editing, event deletion, and prospective workflows.
- Done when: UI/API tests prove history remains visible and replay yields the corrected state.

### S37 — Validate the retrospective vertical slice — done

- Objective: Run the complete PS Min flow from disposable OSCAR input through the local UI and document evidence.
- Excludes: New features, prospective experiments, and AI.
- Done when: Milestones 1–4 exit criteria pass or every remaining gap is recorded as a bounded sprint.

### S37A — Select and normalize the retrospective OSCAR cohort — done

- Objective: Add an explicit local selection contract that reads every chosen PS Min candidate session spanning the historical change from a protected OSCAR copy and produces a deterministic multi-night normalized cohort with settings and correction evidence.
- Excludes: Automatic cohort or change detection, experiment-history mutation, evaluation, UI, prospective workflows, and OSCAR writes.
- Done when: A synthetic multi-night schema-17 fixture proves selected sessions, split-session grouping, settings, signals, raw/corrected-time evidence, provenance, and missing states are reproducible without modifying the source.

### S37B — Record the retrospective protocol and confirmed boundary — queued

- Objective: Persist the exact accepted retrospective proposal and a user-confirmed applied-change boundary for the selected cohort as append-only experiment events.
- Excludes: Inferring confirmation from OSCAR settings, general editing, prospective safety policy, evaluation, UI, and device changes.
- Done when: Replay exposes one effective accepted proposal and confirmed PS Min 2-to-1 boundary linked to the selected cohort while preserving every prior event and refusing unconfirmed or inconsistent input.

### S37C — Link retrospective subjective and confounder evidence — queued

- Objective: Add a bounded local intake/import path for attributable historical journal responses, confounders, and adverse effects, preserving explicit unavailable states and original text.
- Excludes: Prospective morning forms or reminders, NLP or AI interpretation, clinical advice, and silent conversion of missing evidence to negative answers.
- Done when: Replay yields the exact effective per-night user evidence supplied for the retrospective cohort and explicitly distinguishes unavailable, not reported, none reported, and reported states.

### S37D — Orchestrate the retrospective evaluation — queued

- Objective: Deterministically run quality assessment, period allocation, both version-1 metrics, and outcome classification from the selected cohort and effective experiment/user history.
- Excludes: New metrics or thresholds, automatic selection, report presentation, UI, prospective logic, and AI.
- Done when: One integration fixture produces a stable evidence-linked classification or rules-required inconclusive result whose provenance reaches every selected night, quality finding, metric, and effective user event.

### S37E — Build the complete retrospective report and evidence excerpts — queued

- Objective: Build the versioned retrospective report from an S37D evaluation bundle and explicitly selected bounded baseline/intervention waveform excerpts.
- Excludes: Automatic interval selection, arbitrary signal exploration, new calculations, UI changes, prospective workflow, and AI prose.
- Done when: Snapshot tests cover populated and explicitly missing periods, metrics, subjective evidence, quality, classification/action, limitations, and both representative intervals with complete source linkage.

### S37F — Connect and revalidate the retrospective local UI — queued

- Objective: Configure the local API to serve the evaluated retrospective report and effective workspace history, then re-run the Milestone 3 and 4 gates through the packaged localhost UI.
- Excludes: New analytical methods, general editing, prospective workflows, remote access, and AI.
- Done when: A protected disposable end-to-end run links selected OSCAR nights through the deterministic evaluation to every populated UI section, retains honest missing states, persists history across restart, and records explicit Milestone 3 and 4 gate decisions.

## 5 — Prospective experiment support

### S38 — Define prospective safety policy — queued

- Objective: Record the initial settings allowlist, change bounds, exclusions, minimum data, stop rules, and reversion requirements.
- Excludes: Implementation and AI proposals.
- Done when: A safety decision record resolves every required rule or explicitly blocks implementation.

### S39 — Implement the deterministic safety gate — queued

- Objective: Evaluate a prospective proposal against S38 and return structured failures.
- Excludes: UI, AI, and device-setting instructions.
- Done when: Tests prove unsupported, multi-variable, insufficient-data, and missing-reversion proposals are rejected.

### S40 — Implement prospective lifecycle events — queued

- Objective: Support propose, accept/reject/revise, confirm-applied, stop/extend/keep/revert, and supersede events.
- Excludes: Monitoring calculations and UI.
- Done when: Replay tests cover one complete lifecycle and corrections remain additive.

### S41 — Add morning sleep-journal entry — queued

- Objective: Add the smallest local form/API for structured morning outcomes, optional free-text notes, adverse effects, and confounder events.
- Excludes: Notifications, mobile UI, AI or NLP interpretation of journal prose, and free-form clinical advice.
- Done when: Entries validate, append, link to the selected therapy night, and appear in reconstructed experiment state.

### S42 — Add prospective monitoring view — queued

- Objective: Show progress toward valid-night requirements, safety status, outcomes, and available lifecycle actions.
- Excludes: AI and automatic device interaction.
- Done when: A seeded experiment can be proposed, manually confirmed, monitored, and evaluated through the UI.

### S43 — Validate the non-AI prospective flow — queued

- Objective: Exercise one synthetic prospective experiment end to end and record evidence.
- Excludes: Real settings recommendations and AI integration.
- Done when: Milestone 5 exit criterion passes using synthetic or safely staged data.

## 6 — Optional AI assistance

### S44 — Decide the AI data boundary and provider — queued

- Objective: Select one provider and document permitted fields, redactions, credential storage, retention concerns, and whether hosted transmission is acceptable.
- Excludes: API calls and multi-provider abstraction.
- Done when: An explicit decision authorizes a bounded integration or records that AI remains deferred.

### S45 — Implement the structured AI adapter — queued

- Objective: Send only an approved structured summary and bounded waveform excerpts and validate a structured hypothesis/experiment response.
- Excludes: Direct database access, authoritative calculations, and multiple providers.
- Done when: Contract tests cover valid, malformed, refused, and unavailable-provider responses.

### S46 — Enforce the safety gate on AI drafts — queued

- Objective: Route every AI proposal through S39 before presentation and prevent unsafe text from becoming viable.
- Excludes: Prompt tuning and UI polish.
- Done when: Tests prove failed proposals cannot be accepted or activated regardless of AI wording.

### S47 — Record AI provenance — queued

- Objective: Persist provider, model, prompt version, approved inputs, raw structured output, and evidence references as append-only events.
- Excludes: Analytics and provider comparison.
- Done when: A replayed AI-assisted experiment has a complete, inspectable provenance chain.

### S48 — Evaluate AI usefulness — queued

- Objective: Compare AI-assisted exploration/explanation with the deterministic retrospective fixture and document benefit, errors, and limitations.
- Excludes: Expanding recommendation scope.
- Done when: A short evaluation supports enabling, revising, or disabling AI assistance for the prototype.
