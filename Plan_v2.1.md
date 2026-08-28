# PAP Optimization Companion — Personal Prototype Plan (v2.1)

**Status:** Personal-use-first implementation plan  
**Date:** August 27, 2026  
**Governs:** The personal prototype phase  
**Related documents:** `PAP_Optimization_Product_Plan.md` (v1) remains the future-product and distribution requirements reference. `PAP_Optimization_Plan_v2.md` is superseded by this document.  
**Working name:** To be selected before development begins; PAP Optimization Companion is a placeholder until that decision is recorded.

---

## 1. Purpose

Build a useful single-user tool before investing in infrastructure needed for distribution. The prototype will analyze OSCAR-normalized PAP data, evaluate controlled settings experiments, combine objective and subjective outcomes, and present the evidence through a clean local interface.

The primary unit remains **an evaluated therapy experiment**, not a chart, score, night, or AI conversation.

The earlier v1 requirements for multi-user safety, mobile access, synchronization, MCP, licensing, regulatory review, and commercialization are retained as a future reference. They are not current implementation requirements.

---

## 2. What the existing PS Min experiment establishes

The informal change from PS Min 2 to PS Min 1 is a strong initial use case. It suggests that AI-assisted analysis of OSCAR-derived data can produce a useful hypothesis and a subjectively meaningful result.

It does **not** yet establish that:

- The change caused the improvement rather than normal night-to-night variation or a confounder.
- The calculated metrics were implemented correctly.
- The same reasoning will work for a different therapy problem.
- The evaluation method can reliably distinguish improvement from regression to the mean.
- Future AI-generated recommendations will be safe or useful.

Therefore, the PS Min experiment will be the prototype's first retrospective validation fixture. The initial vertical slice should reproduce its baseline and intervention periods, calculate predefined outcomes, incorporate the user's reports, and determine whether explicit evaluation rules reach a defensible conclusion.

---

## 3. Confirmed architecture and safety boundaries

### 3.1 OSCAR remains required

- OSCAR 2 performs SD-card import, device decoding, normalization, duplicate handling, clock correction, and canonical PAP-data storage.
- The companion reads OSCAR's SQLite database through a separate read-only adapter.
- The companion does not parse raw ResMed EDF files initially.
- The companion never writes to OSCAR's database.
- The normal OSCAR GUI import workflow is acceptable during the personal prototype phase.
- A headless OSCAR importer remains deferred.

### 3.2 Initial database-use rule

Until concurrent-read behavior has been investigated and tested, **OSCAR must be closed before the companion reads its database**.

The adapter must:

- Open the database explicitly in read-only mode.
- Refuse unknown or unsupported schema versions.
- Avoid schema changes, temporary-table writes, maintenance operations, and repair commands.
- Read a consistent snapshot.
- Preserve OSCAR and machine provenance.
- Fail safely on locks, integrity errors, missing channels, or incomplete sessions.

Early development must use a backup or disposable copy until read-only behavior has been verified.

### 3.3 Deterministic engine remains independent

- Data mapping, metrics, comparisons, safety checks, experiment evaluation, and report calculations live outside the UI and AI code.
- Identical inputs and engine versions must produce identical results.
- Every derived value records its source, units, time range, algorithm version, quality status, and limitations.

### 3.4 AI is advisory

- AI may identify possible problems, explain evidence, rank hypotheses, and draft one-variable experiments.
- AI does not calculate authoritative metrics when deterministic code can do so.
- AI does not read the OSCAR database directly.
- AI does not activate experiments or change the PAP device.
- Every proposal must pass deterministic eligibility and safety checks before it is presented as a viable experiment.
- Every settings change is reviewed and applied manually outside the application.

---

## 4. Scope of the personal prototype

### In scope

- One known user and one OSCAR profile.
- ResMed AirCurve 10 ASV data already normalized by OSCAR 2.
- A local web application bound only to the local machine.
- Python backend, preferably FastAPI with explicit request and response models.
- A browser-based interface focused on experiments and supporting evidence.
- Read-only OSCAR adapter.
- Deterministic metrics and before-and-after comparisons.
- Append-only experiment history.
- Brief subjective outcome and confounder logging.
- One configured AI provider after the deterministic vertical slice works.
- Manual settings application and explicit confirmation of when a change was applied.

### Deferred

- Mobile application.
- Cloud synchronization and multi-device workspaces.
- Multi-user accounts, permissions, or sharing.
- MCP server and external AI clients.
- Provider-neutral AI adapters and local Ollama integration.
- Headless OSCAR importing.
- Support for additional PAP machines, modes, or profiles.
- Formal regulatory, clinical, and legal review for distribution.
- Open-source governance, licensing strategy, business model, final branding, and external name clearance.

---

## 5. OSCAR integration research

The first technical task is to use OSCAR's supported external-data materials rather than begin with reverse engineering.

1. Obtain the OSCAR 2 SQL Notes and official Python demonstration.
2. Locate the active OSCAR 2.0.1 database and record its schema version.
3. Back up the database and run the demonstration against the copy.
4. Document only the tables, columns, identifiers, units, encodings, and relationships needed for the AirCurve 10 ASV prototype.
5. Map profiles, machines, sessions, settings, signals, events, and time corrections into the internal model.
6. Inspect OSCAR's source only where the published documentation is incomplete.
7. Record all assumptions that may change with a future OSCAR schema version.

Reading raw EDF files is a last-resort fallback, not an alternate starting path.

---

## 6. Minimum validation required now

Formal product validation is deferred, but personal use still requires confidence that the software is reading and calculating the right things.

The prototype must include:

- Cross-checks against OSCAR for settings, session boundaries, timestamps, event counts, waveform values, and summary statistics.
- Fixed test nights with expected outputs that cannot change silently.
- Versioned definitions for each metric and threshold.
- Tests for units, missing samples, clock corrections, short or split sessions, large leak, signal artifacts, and likely wake breathing.
- Explicit distinction among machine-recorded, OSCAR-derived, companion-derived, AI-generated, and user-reported information.
- An `insufficient evidence` result when quality or sample-size requirements are not met.
- Storage of engine, rule-set, and prompt versions with every experiment evaluation.

The initial metric set should remain deliberately small. A metric is added only when it supports a defined hypothesis or experiment decision.

---

## 7. Experiment and safety model

Each experiment record must include:

- Problem being investigated.
- Hypothesis and competing explanations.
- Baseline dates and settings.
- Proposed single-variable change.
- Settings held fixed.
- Evidence and representative waveform intervals.
- Expected objective and subjective effects.
- Minimum valid nights and invalid-night criteria.
- Possible adverse effects.
- Stop and revert conditions.
- What was actually applied and when.
- Confounders and subjective reports.
- Final classification and next action.

Initial classifications are:

- Clear improvement.
- Probable improvement.
- Mixed tradeoff.
- No meaningful change.
- Probable worsening.
- Inconclusive.

The deterministic safety gate must, at minimum:

- Allow only explicitly supported settings and change ranges.
- Reject mode changes and starting or stopping ASV.
- Reject proposals without sufficient usable data.
- Reject proposals that alter more than one primary variable.
- Require explicit stop and reversion rules.
- Prevent AI text from overriding a failed eligibility or safety check.

The initial supported recommendation scope must be defined before the app drafts a new prospective experiment.

---

## 8. Experiment storage

Experiment history must be additive and auditable. SQLite is preferred over loose JSON once implementation begins, provided changes are represented as new events rather than destructive overwrites.

Minimum event types include:

- Problem recorded.
- Hypothesis drafted.
- Experiment proposed, accepted, rejected, or revised.
- Setting change confirmed as applied.
- Morning outcome recorded.
- Confounder or adverse effect recorded.
- Experiment stopped, extended, kept, or reverted.
- Evaluation issued or superseded.

Corrections create new events that reference the prior record. They do not erase history.

---

## 9. First vertical slice: PS Min 2 to PS Min 1

The first milestone is an end-to-end retrospective evaluation of the known PS Min experiment.

The prototype must:

1. Read the relevant nights and settings from OSCAR.
2. Detect or confirm the exact settings-change boundary.
3. Assign nights to baseline and intervention periods.
4. Exclude or flag nights that fail predefined quality criteria.
5. Calculate a small predefined set of objective outcomes.
6. Incorporate reported awakenings, sleep quality, morning energy, daytime tiredness, travel, and other known confounders where available.
7. Show representative baseline and intervention waveform segments.
8. Produce an evaluation with evidence, uncertainty, and limitations.
9. Determine whether the rules support keeping, reverting, extending, or classifying the experiment as inconclusive.
10. Display the complete experiment in the local UI.

Success means that the tool reproduces the evidence transparently and reaches a defensible conclusion. Success does not require it to agree with the earlier informal interpretation.

---

## 10. Development sequence

### Milestone 0: Working identity and continuity

- Select the working product name and technical identifiers.
- Record the naming rationale and explicitly deferred clearance work.
- Initialize version control and create the first clean planning checkpoint.

**Exit criterion:** The working name and identifiers are explicitly approved and used consistently, and the planning baseline is committed without sensitive files.

### Milestone 1: OSCAR read feasibility

- Run the official SQL demonstration.
- Document the required schema subset.
- Build a strictly read-only adapter.
- Cross-check one night against OSCAR.

**Exit criterion:** Required AirCurve 10 ASV signals, settings, sessions, and events can be extracted reproducibly without modifying OSCAR data.

### Milestone 2: Normalized model and fixtures

- Define internal records for nights, sessions, settings, signals, events, and provenance.
- Add fixed reference nights and expected outputs.
- Implement quality and exclusion flags.

**Exit criterion:** Imported values and timestamps agree with OSCAR for the reference nights.

### Milestone 3: Retrospective experiment engine

- Define the experiment and event schemas.
- Implement baseline/intervention allocation.
- Implement the first metrics and outcome classification rules.
- Reconstruct the PS Min experiment.

**Exit criterion:** The engine produces a reproducible, evidence-linked evaluation without AI.

### Milestone 4: Local web interface

- Show experiment status, periods, metrics, subjective outcomes, representative waveforms, and final evaluation.
- Allow manual correction of experiment boundaries and addition of notes without destroying history.
- Bind the service only to the local machine by default.

**Exit criterion:** The PS Min experiment can be reviewed from beginning to end through the UI.

### Milestone 5: Prospective experiment support

- Define the initial settings allowlist, bounds, validity rules, stop rules, and reversion requirements.
- Support starting and monitoring one prospective experiment.
- Add brief subjective and confounder entry.

**Exit criterion:** A complete experiment can be proposed, manually applied, monitored, and evaluated without AI.

### Milestone 6: Optional AI assistance

- Configure one AI provider and define exactly what information may be transmitted.
- Give the model structured summaries and bounded waveform excerpts, not direct database access.
- Require structured hypothesis and experiment drafts.
- Run every draft through the deterministic safety gate.
- Record provider, model, prompt version, tool inputs, output, and evidence references.

**Exit criterion:** AI adds useful exploration or explanation without becoming authoritative for calculations or bypassing safety rules.

---

## 11. Decisions still required during the prototype

- Exact OSCAR 2.0.1 schema subset and read contract.
- Internal serialization and local database schema.
- Initial objective metrics and their definitions.
- Valid-night criteria and minimum baseline/intervention duration.
- Subjective questionnaire and required confounders.
- Initial settings recommendation allowlist, change bounds, and exclusions.
- Outcome weighting and classification thresholds.
- Choice of the first AI provider and whether health data may be sent to a hosted service.
- Credential storage and AI data-minimization rules.
- Local backup and recovery approach for the experiment database.

These decisions should be recorded as short architecture or methodology decision records as they are made.

---

## 12. Immediate next actions

1. Select and record the working product name and technical identifiers.
2. Initialize version control and create the planning baseline.
3. Obtain OSCAR's SQL Notes and Python demonstration.
4. Make a protected backup of the current OSCAR database.
5. Locate the database and record the OSCAR and schema versions.
6. Run the demonstration against the backup.
7. Document the AirCurve 10 ASV schema subset needed for the first experiment.
8. Cross-check one selected night against OSCAR.
9. Define the normalized records and experiment event schema.
10. Reconstruct the PS Min 2-to-1 experiment as the first vertical slice.

No AI integration or broad UI work begins until the deterministic retrospective evaluation works end to end.
