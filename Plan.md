# PAP Optimization Companion — Unified Plan

**Status:** Living product and implementation plan
**Created:** August 27, 2026
**Updated:** August 28, 2026
**Governs:** The personal prototype; deferred future-product requirements are retained in Part II
**Working name:** To be selected before development begins; PAP Optimization Companion is a placeholder until that decision is recorded.

This is the single authoritative plan. Part I governs current work. Part II
preserves future distribution requirements and possibilities; it does not
expand the personal prototype unless a later decision explicitly promotes an
item into Part I and the sprint queue.

Update this file in place as decisions change. Use Git history and focused
decision records for provenance rather than creating additional versioned plan
documents.

`SPRINTS.md` is the authoritative implementation queue. This plan defines
scope, requirements, safety boundaries, and milestone exit criteria; it does
not track sprint identifiers, ordering, or status. `STATUS.md` records the
current handoff state.

# Part I — Personal Prototype

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

These milestones are outcome gates, not a task queue. The current order and
status of the work needed to reach them lives only in `SPRINTS.md`.

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

## 12. Execution source of truth

Use `SPRINTS.md` for the ordered work queue, sprint scope, exclusions,
completion checks, and status. Use `STATUS.md` for the current handoff,
validation evidence, decisions, and blockers. Update this plan only when the
product scope, requirements, safety boundaries, architecture, or milestone
gates change.

The deterministic retrospective evaluation must still work end to end before
AI integration or broad UI work begins.

---

# Part II — Deferred Future Product and Distribution Plan

**Status:** Deferred reference; not current prototype scope
**Original concept date:** August 16, 2026

This part retains the broader product concept for possible future distribution. Statements described below as confirmed or proposed belong to that future-product context. If Part II conflicts with Part I, Part I controls. No Part II item becomes active until an explicit decision promotes it into Part I and SPRINTS.md. Original section numbers are prefixed with F.

## F2. Executive summary

The proposed product is a privacy-conscious desktop and mobile companion for people using positive airway pressure therapy, with an initial emphasis on adaptive servo-ventilation (ASV).

It is not intended to replace OSCAR. OSCAR remains responsible for importing PAP SD-card data, decoding device formats, normalizing therapy records, maintaining the canonical PAP database, and displaying detailed breathing results. The proposed product will build on OSCAR's work through a read-only adapter.

The product's primary function is a closed-loop optimization process:

1. Analyze a baseline period.
2. Identify the most important unresolved therapy problem.
3. Explain the evidence, including representative waveforms.
4. Propose one controlled settings experiment.
5. Have the user review and deliberately apply the change outside the app.
6. Collect several nights of new data plus subjective outcomes.
7. Determine whether the experiment helped, harmed, or produced an inconclusive result.
8. Recommend keeping, reverting, extending, or replacing the experiment.
9. Repeat as appropriate.

The analysis engine will be separate from every graphical interface and from every AI model. Deterministic code will parse normalized data, calculate metrics, evaluate comparisons, and enforce safety policies. Optional AI will ask novel questions, investigate evidence through a Model Context Protocol (MCP) server, explain findings, and draft hypotheses or experiments. AI will not directly modify the PAP machine or bypass confirmation and safety controls.

Desktop and mobile applications will share a synchronized therapy workspace containing experiment state, subjective reports, selected evidence, AI interaction records, and analysis results. Raw waveform data will remain local by default unless the user chooses another storage mode.

---

## F3. Problem statement

PAP devices and existing applications provide valuable data, but they often stop at visualization and summary statistics. Many users receive limited help interpreting detailed waveforms, investigating persistent symptoms despite a low reported AHI, choosing a controlled settings experiment, or determining objectively whether a change worked.

Clinical support can also be limited by appointment availability, time constraints, uneven clinician interest in high-resolution PAP data, and limited familiarity with specialized therapy modes. This creates a gap between seeing data and learning from it over time.

The product should address five connected problems:

- Important breathing patterns may not be captured adequately by AHI alone.
- Users may not understand how a displayed waveform differs from their own stable breathing.
- Settings changes are often made without a documented hypothesis or controlled evaluation.
- Objective PAP data and subjective outcomes are rarely analyzed together.
- AI can generate useful questions and interpretations, but it needs controlled access to reproducible evidence and safety boundaries.

---

## F4. Product thesis

> An explainable, closed-loop PAP and ASV optimization companion that uses OSCAR-normalized data to identify problems, propose controlled settings experiments, measure objective and subjective outcomes, and iteratively determine what works.

The product's primary unit is an **evaluated therapy experiment**, not a chart, score, night, or AI conversation.

---

## F5. Confirmed decisions

The following decisions are considered settled unless a substantive review identifies a reason to reopen them.

### F5.1 OSCAR is required

- OSCAR will be required for PAP SD-card ingestion.
- OSCAR will own device detection, decoding, validation, duplicate handling, normalization, and its canonical PAP database.
- The product will not attempt to replace OSCAR as the primary detailed PAP waveform viewer.
- The product will not initially build a competing raw ResMed SD-card parser.
- The product will access OSCAR data through a separate, read-only adapter.
- The product will not write directly into OSCAR SQL tables.
- OSCAR 2 is the initial integration target because it uses SQL storage and provides access for other programs.

### F5.2 Import should not require opening OSCAR manually

The desired experience is:

1. Insert or update the PAP SD card or its selected archive.
2. Open the proposed application.
3. The application invokes OSCAR's import machinery without displaying the OSCAR GUI.
4. OSCAR safely updates its own database using its loaders and locks.
5. The proposed application reads the completed import.

The preferred implementation is an official headless OSCAR importer contributed upstream. A separately maintained GPL-compatible helper based on OSCAR's importer is a fallback, not the first choice. GUI automation and unapproved direct database writes are rejected approaches.

### F5.3 The analysis engine is separate from the GUI

- The core engine must not depend on Tauri, React, mobile layouts, or any graphical framework.
- The engine will expose a stable, versioned API.
- A command-line interface will exercise the same engine used by desktop, mobile, reports, and AI tools.
- Identical inputs and engine versions must produce identical deterministic results regardless of interface.

### F5.4 The product complements OSCAR

- OSCAR remains available for detailed manual waveform exploration.
- The companion application will link findings to precise dates, sessions, and time intervals that can be inspected in OSCAR.
- The companion will concentrate on hypothesis formation, settings experiments, outcome collection, comparison, interpretation, and longitudinal learning.

### F5.5 Desktop and mobile share state

- Interactions on desktop and mobile must contribute to the same therapy history.
- The current experiment, user decisions, symptom logs, analysis results, reports, and saved AI insights must synchronize.
- Meaningful interactions will be stored as an append-only or equivalently auditable event history.
- Conflicting decisions must be shown to the user rather than silently overwritten.

### F5.6 A separate cloud workspace is authoritative for optimization state

- OSCAR's active data directory will not be used as the application's writable cloud workspace.
- The product will maintain its own synchronized workspace.
- OSCAR and the SD card are data sources; the companion workspace is the authoritative record of optimization activity.
- Storage access will be provider-neutral: local synchronized folders, iCloud Drive, Google Drive, Dropbox, OneDrive, WebDAV, network storage, or future connectors may be supported through adapters.

### F5.7 Waveforms must be explanatory

The product will show more than the observed waveform. It should show:

- The user's actual waveform and synchronized pressure, leak, and related signals.
- Breath-level annotations and confidence.
- Why a segment was selected.
- A comparison with the user's own stable breathing when possible.
- A mode-appropriate educational reference.
- A clearly labeled simulated improvement where useful.
- The expected waveform effect of a proposed experiment.
- The actual before-and-after waveform result.

The product must not imply that one universal ideal waveform applies to every user, sleep stage, body position, or therapy mode.

### F5.8 Recommendations are controlled experiments

- Recommendations may include explicit settings changes.
- One primary variable should normally change per experiment.
- Every recommendation must include its hypothesis, evidence, expected effect, evaluation period, possible downsides, stop conditions, and reversion plan.
- The app will never change PAP settings remotely.
- The user must deliberately review and apply any setting change outside the application.
- Mode changes, starting or stopping ASV, and other high-risk actions are outside ordinary recommendation scope.

### F5.9 AI is optional and model-neutral

- The deterministic engine remains authoritative for calculations.
- AI may investigate, explain, generate questions, rank hypotheses, and draft experiments.
- AI may not invent measurements or bypass safety controls.
- The official AI boundary will be an MCP server.
- The built-in AI chat, if enabled, will use the same MCP tools available to external AI clients.
- The product should support local Ollama, hosted model APIs, OpenAI-compatible endpoints, external MCP clients, and portable consultation packages.
- Direct model authentication and external MCP access are complementary options.

### F5.10 Working identity now; external clearance later

The personal prototype selects a stable working name and technical identifiers
before scaffolding begins, as required by Part I. Final trademark, app-store,
domain, social-handle, and legal clearance remains deferred until public
distribution or branding is considered.

---

## F6. Proposed user experience

### F6.1 Initial setup

1. Install OSCAR 2 and the companion desktop application.
2. Select the OSCAR profile and grant read-only access.
3. Select or create the companion workspace.
4. Choose a synchronization location and privacy mode.
5. Complete safety screening and therapy-profile questions.
6. Optionally connect symptom sources, oximetry, wearables, and AI providers.
7. Import or identify sufficient baseline data.

### F6.2 Routine data import

1. The user inserts the PAP SD card or updates its designated source folder.
2. The desktop app detects new source data.
3. It invokes the supported OSCAR headless importer.
4. OSCAR imports and validates new sessions.
5. The adapter reads newly available normalized data.
6. The engine performs incremental analysis.
7. The workspace records the import and analysis versions.
8. Desktop and mobile display what changed.

### F6.3 Baseline analysis

The engine should evaluate:

- Usage and signal quality.
- Machine-reported events and settings.
- Leak burden and artifact.
- Breath morphology and flow limitation.
- Ventilation stability and periodicity.
- Pressure and pressure-support response.
- Time near configured limits.
- RERA-like disturbances and recovery breathing, with clear uncertainty.
- Timing, clustering, sleep-wake contamination, and possible confounders.
- Longitudinal trends and setting-change boundaries.
- Subjective sleep quality, fatigue, awakenings, and side effects.

The output should identify the dominant problem, alternative explanations, missing information, and whether a settings experiment is justified.

### F6.4 Experiment proposal

Each proposal must state:

- Problem being addressed.
- Hypothesis.
- Proposed single-variable change.
- Settings that remain fixed.
- Evidence and representative waveform segments.
- Confidence and limitations.
- Expected objective changes.
- Expected subjective changes.
- Potential adverse effects.
- Required number of valid nights.
- Stop and revert criteria.
- Conditions making the experiment invalid.

### F6.5 Experiment execution

- The user reviews and accepts, rejects, or modifies the draft.
- Acceptance records the original and proposed settings.
- The user confirms when the change was actually applied.
- Mobile reminders request brief morning outcome reports.
- New nights are associated with the correct experiment only after the confirmed application time.
- Confounding changes are recorded.

### F6.6 Experiment evaluation

The result should be classified as:

- Clear improvement.
- Probable improvement.
- Mixed tradeoff.
- No meaningful change.
- Probable worsening.
- Inconclusive.

The app should recommend:

- Keep the new setting.
- Revert to the prior setting.
- Extend data collection.
- Test the next hypothesis.
- Stop self-directed experimentation and seek clinical assessment.

The result must combine objective and subjective evidence. Lower AHI or a better waveform score is not automatically a success if sleep quality, awakenings, leak, aerophagia, discomfort, or another important outcome worsens.

---

## F7. Proposed architecture

### F7.1 Major components

| Component | Responsibility |
|---|---|
| OSCAR | SD-card import, device loaders, normalized PAP storage, detailed visualization |
| Headless OSCAR importer | Safe GUI-free invocation of OSCAR's existing import process |
| OSCAR adapter | Read-only translation from OSCAR's schema into the internal model |
| Analysis engine | Deterministic signal, metric, hypothesis, comparison, and report calculations |
| Experiment engine | Proposal, eligibility, monitoring, evaluation, and next-action logic |
| Safety policy engine | Screening, prohibited actions, stop rules, and escalation rules |
| Engine API | Stable versioned contract independent of language and GUI |
| CLI | Testing, batch analysis, debugging, research, and reproducibility |
| Desktop app | Import orchestration, detailed review, experiment management, reports |
| Mobile app | Status, questions, symptom logging, reminders, reports, selected waveforms |
| Workspace | Synchronized experiments, results, events, notes, evidence, and reports |
| MCP server | Model-neutral AI tools, resources, prompts, and permission enforcement |
| AI provider adapters | OpenAI, Anthropic, Gemini, Ollama, and compatible endpoints |

### F7.2 Technology direction

**Working assumption:** Use Tauri 2 for desktop and mobile application shells, a web-based interface, and Rust for production engine components where practical.

Reasons:

- Tauri supports Windows, macOS, Linux, iOS, and Android.
- Rust can provide efficient processing and clean library boundaries.
- A shared front-end can reduce duplicated interface work.
- Native Swift and Kotlin plugins remain available for platform-specific storage and authentication.

Scientific algorithms may be prototyped in Python, but accepted production behavior must have stable fixtures and reproducible implementation. A later wholesale rewrite of medically relevant logic should be avoided unless independently validated.

### F7.3 Suggested repository structure

```text
pap-companion/
├── engine/
│   ├── model/
│   ├── signals/
│   ├── metrics/
│   ├── hypotheses/
│   ├── experiments/
│   ├── safety/
│   └── reports/
├── oscar-adapter/
├── engine-api/
├── cli/
├── mcp-server/
├── sync/
├── desktop/
├── mobile/
├── research/
├── fixtures/
└── documentation/
```

### F7.4 Internal data provenance

Every finding must identify its source class:

- Machine-recorded.
- Machine-labeled.
- OSCAR-normalized or OSCAR-derived.
- Companion-engine-derived.
- AI-generated interpretation.
- User-reported.
- External sensor or wearable.

Every derived result should retain:

- Source record identifiers.
- Date and time interval.
- Algorithm and engine version.
- Units.
- Confidence or quality status.
- Exclusions and limitations.
- Links to supporting waveform intervals.

---

## F8. OSCAR integration plan

### F8.1 Desired contract

The preferred OSCAR contribution is a supported headless command or library interface equivalent to:

```bash
oscar-import --profile <profile> --source <sd-card-path> --json-result
```

It should:

- Acquire OSCAR's ordinary database lock.
- Use OSCAR's existing device loaders.
- Import only valid new sessions.
- Apply OSCAR's duplicate, repair, indexing, and summary logic.
- Report progress and structured errors.
- Exit without opening the graphical interface.

### F8.2 Adapter responsibilities

The read-only OSCAR adapter should:

- Detect supported OSCAR schema versions.
- Reject unknown incompatible versions safely.
- Map profiles, devices, sessions, channels, settings, events, and annotations.
- Preserve OSCAR and machine provenance.
- Read consistent snapshots rather than partially written state.
- Cache only what is required for efficient incremental analysis.
- Never modify OSCAR-managed data.

### F8.3 Fallbacks

Until headless import is available:

- The user may need to perform the import through OSCAR manually.
- The companion can detect when OSCAR contains new data and continue automatically from that point.
- A GPL helper derived from OSCAR code may be evaluated only after licensing and maintenance review.

Rejected fallbacks:

- Automating OSCAR mouse clicks.
- Reverse-engineered direct inserts into OSCAR SQL.
- Building a full competing family of device loaders as the initial product.

---

## F9. Workspace and synchronization

### F9.1 Workspace contents

```text
PAP-Companion/
├── workspace.json
├── events/
├── sources/
├── normalized-results/
├── analyses/
├── experiments/
├── symptoms/
├── ai-insights/
├── evidence/
└── reports/
```

The exact physical format is undecided. The logical requirements are stable identity, versioning, atomic updates, encryption options, conflict detection, and recovery.

### F9.2 Synchronization behavior

On launch, each application should:

1. Reconnect to the selected workspace.
2. Read a small manifest or journal head rather than scan all files.
3. Download new state and verify hashes.
4. Merge nonconflicting events.
5. Surface true conflicts.
6. Perform permitted local analysis.
7. Upload new events and results atomically.

### F9.3 Mobile role

Initial mobile capabilities should include:

- Current experiment status.
- Confirmation that a setting was applied.
- Morning symptom and sleep-quality reports.
- Side-effect and confounder logging.
- AI questions and saved insights.
- Before-and-after results.
- Selected waveform evidence.
- Reports and reminders.

Full raw-waveform processing on mobile is not required for the first release.

---

## F10. MCP and AI architecture

### F10.1 MCP as the official AI boundary

The MCP server should expose controlled access to the engine rather than direct database access.

Initial read-only tools may include:

- `get_current_therapy_status`
- `query_nights`
- `get_settings_history`
- `get_signal_statistics`
- `find_waveform_segments`
- `get_waveform_excerpt`
- `analyze_pressure_response`
- `compare_cohorts`
- `compare_experiment`
- `correlate_variables`
- `explain_metric`

Controlled write tools may include:

- `save_question`
- `save_insight`
- `draft_hypothesis`
- `draft_experiment`
- `attach_note_to_experiment`

MCP must not expose tools to activate an experiment, modify PAP settings, delete therapy history, or bypass application review.

### F10.2 AI access modes

| Mode | Description |
|---|---|
| Built-in local AI | The app uses Ollama or another local endpoint; data can remain local |
| Built-in hosted AI | User supplies provider API credentials; selected context is transmitted |
| External local MCP | Compatible desktop AI client connects to the local MCP server |
| External remote MCP | Compatible desktop or mobile AI client connects through authenticated HTTPS |
| Consultation package | User exports a bounded package to any AI interface manually |

### F10.3 AI safety and evidence requirements

- AI-generated claims must cite engine evidence identifiers when possible.
- AI may propose an unanticipated relationship, but the engine must calculate the supporting comparison.
- AI output must display provider, model, date, and applicable engine/prompt versions.
- Model responses are interpretations, not source measurements.
- The server should minimize data returned and use bounded waveform windows, pagination, and downsampling.
- External AI clients may not expose their full conversation to MCP. Saving an insight must therefore be an explicit action.

---

## F11. Safety, clinical boundaries, and human control

This is a high-risk area requiring specialist review.

### F11.1 Proposed safeguards

- Initial screening for known contraindications and conditions making self-directed changes inappropriate.
- Prominent ASV-specific safety screening.
- No remote control of PAP equipment.
- No automatic activation of settings experiments.
- One primary change at a time by default.
- Small, bounded changes within configured and policy limits.
- Original settings preserved with a clear reversion plan.
- Stop rules for worsening symptoms, respiratory patterns, leaks, intolerance, or other concerning signals.
- Clear separation between educational explanation, experiment proposal, and medical advice.
- Audit log of recommendations, evidence, user decisions, and outcomes.
- Ability to generate a clinician-facing report at any point.

### F11.2 Prohibited or highly restricted actions

- Recommending that a user start or stop ASV independently.
- Recommending a change of therapy mode without qualified review.
- Concealing uncertainty or presenting estimated sleep state or arousals as confirmed.
- Treating low AHI as proof of effective therapy.
- Treating a derived waveform score as a diagnosis.
- Continuing experiments after predefined stop criteria are met.
- Allowing an AI model to issue an unreviewed settings instruction.

### F11.3 Regulatory review

Because the product may recommend therapy-setting changes and evaluate their effects, it may fall within medical-device or clinical decision-support regulation in one or more jurisdictions. Disclaimers alone may not determine classification.

Before public release, obtain qualified review covering at least:

- Intended use and product claims.
- FDA software functions and clinical decision support analysis.
- EU Medical Device Regulation implications.
- UK and other target-market requirements.
- Quality-management expectations.
- Risk management and human-factors testing.
- Post-market monitoring and adverse-event handling.
- Whether settings recommendations require a regulated development path.

---

## F12. Validation strategy

### F12.1 Parser and adapter validation

- Compare adapter outputs against OSCAR displays and exports.
- Verify sessions, timestamps, units, settings, signals, and event labels.
- Test across OSCAR schema versions that are claimed as supported.
- Confirm safe behavior when OSCAR is open, locked, upgrading, incomplete, or corrupted.

### F12.2 Signal-analysis validation

- Maintain synthetic signals with known expected properties.
- Maintain de-identified real-world fixtures with expert annotations where permitted.
- Compare calculated metrics with published definitions and reference implementations.
- Measure sensitivity to leak, artifact, wake breathing, missing samples, and clock errors.
- Version every algorithm and threshold.
- Prevent test fixtures from being silently replaced when outputs change.

### F12.3 Experiment-evaluation validation

- Test false improvement caused by regression to the mean.
- Account for night-to-night variability and inadequate sample size.
- Identify confounding setting, medication, altitude, illness, alcohol, mask, and schedule changes.
- Evaluate objective and subjective discordance.
- Require an inconclusive classification when evidence is insufficient.
- Test stop and reversion rules before testing optimization benefits.

### F12.4 AI validation

- Verify that factual claims trace to tool results.
- Test attempts to bypass safety policies.
- Test hallucinated settings, units, dates, and causal claims.
- Compare behavior across supported providers and local models.
- Ensure unsupported tool calls fail safely.
- Maintain scenario-based evaluations for common and adversarial questions.

---

## F13. Proposed development phases

### Phase 0: External review and feasibility

**Deliverables**

- Reviewed product requirements.
- OSCAR architecture and licensing assessment.
- Headless-import feasibility report.
- Preliminary regulatory classification assessment.
- Initial clinical safety review.
- Data-use and consent principles.
- Decision register resolving critical open questions.

**Exit criteria**

- No unresolved issue that could invalidate the core architecture.
- Agreement on initial user population and recommendation scope.
- Agreement on whether a settings-recommendation product is viable under the intended regulatory and risk posture.

### Phase 1: OSCAR adapter and normalized model

**Deliverables**

- Read-only OSCAR 2 adapter.
- Stable normalized data schema.
- Provenance model.
- CLI capable of listing profiles, nights, sessions, settings, signals, and events.
- Golden fixtures and compatibility tests.

**Exit criteria**

- Reproducible extraction from supported OSCAR versions.
- Verified agreement with OSCAR for selected reference data.
- No writes to OSCAR data.

### Phase 2: Deterministic baseline engine

**Deliverables**

- Signal-quality assessment.
- Core PAP/ASV metrics.
- Waveform segment selection and annotations.
- Longitudinal comparisons.
- Machine/OSCAR/engine provenance display.
- CLI baseline report.

**Exit criteria**

- Expert review of representative reports.
- Known limitations documented.
- Repeatable results with versioned fixtures.

### Phase 3: Experiment engine

**Deliverables**

- Hypothesis representation.
- Experiment proposal schema.
- Eligibility and safety checks.
- Baseline/intervention allocation.
- Subjective outcome schema.
- Evaluation classifications.
- Reversion and stop rules.
- Experiment ledger and reports.

**Exit criteria**

- Retrospective simulations behave appropriately.
- Unsafe and insufficient-data scenarios do not generate ordinary recommendations.
- Clinical and regulatory reviewers approve the limited initial scope.

### Phase 4: Desktop application

**Deliverables**

- OSCAR profile connection.
- Import-status orchestration.
- Baseline and experiment interfaces.
- Actual/stable/reference waveform comparisons.
- User review and confirmation workflow.
- Local workspace and reporting.

**Exit criteria**

- Complete experiment cycle without AI.
- Usability testing demonstrates that users understand evidence, uncertainty, and reversion.

### Phase 5: MCP and optional AI

**Deliverables**

- Local MCP server.
- Read-only analytical tools and resources.
- Controlled insight and draft tools.
- Built-in chat using MCP.
- Ollama adapter.
- At least one hosted API adapter.
- Evidence-linked answer display and AI audit records.

**Exit criteria**

- AI cannot bypass experiment activation or safety policies.
- Local-only configuration functions without hosted AI.
- Tool results are bounded, reproducible, and provenance-rich.

### Phase 6: Synchronization and mobile

**Deliverables**

- Provider-neutral workspace connector interface.
- Conflict-safe event synchronization.
- Mobile symptom logging and experiment status.
- Mobile reports, selected waveforms, and built-in AI access.
- Optional authenticated remote MCP.

**Exit criteria**

- Desktop and mobile converge on the same experiment state.
- Offline edits merge or produce understandable conflicts.
- External clients can be revoked and audited.

### Phase 7: Headless OSCAR integration and broader support

**Deliverables**

- Upstream OSCAR headless-import contribution or approved fallback.
- Seamless import without opening the OSCAR GUI.
- Compatibility monitoring for new OSCAR releases.
- Expansion plan for additional PAP modes and devices already normalized by OSCAR.

---

## F14. Open decisions requiring review

### F14.1 Product and audience

- **Initial population:** ASV users only, or ASV-first with limited CPAP/bilevel support?
- **Experience level:** Advanced self-managing users, general PAP users, clinicians, or separate modes?
- **Geography:** Which jurisdiction is the initial release intended for?
- **Age:** Adults only initially?
- **Care relationship:** Is clinician participation optional, encouraged, or required for certain experiments?
- **Accessibility:** What visual, motor, cognitive, and language requirements apply?

### F14.2 Recommendation scope

- Which settings may version 1 recommend changing?
- Should EPAP be supported before PS Min, PS Max, and maximum IPAP?
- Which therapy modes are excluded?
- What change increments and absolute limits are permitted?
- Which user conditions disable settings recommendations entirely?
- Can the tool recommend reverting to a previously successful configuration automatically as a draft?
- When must the output stop at “questions for a clinician” rather than a settings proposal?

### F14.3 Experiment methodology

- Minimum baseline duration.
- Minimum intervention duration.
- Required number of valid nights.
- Definition of a valid night.
- Handling of naps and split sessions.
- Wash-in or adaptation period after a change.
- Outlier handling.
- Missing-data handling.
- Rules for early stopping.
- Rules for extending an inconclusive experiment.
- Clinically meaningful effect sizes.
- How multiple outcomes are weighted.
- How night-to-night variability and regression to the mean are handled.

### F14.4 Objective outcomes

- Exact primary and secondary metrics for each hypothesis.
- Role of AHI and machine event labels.
- Definitions of flow limitation, periodicity, instability, recovery breathing, intervention burden, and pressure-response lag.
- Whether and how sleep-wake contamination is estimated.
- How to reconcile conflicting metrics, such as machine flow-limitation output and independent breath-shape scores.
- Thresholds versus personalized baselines.
- Use of oximetry and heart rate.
- Use of wearable sleep stages, acknowledging their limitations.

### F14.5 Subjective outcomes

- Minimum morning questionnaire.
- Scales for energy, sleepiness, awakenings, sleep quality, comfort, aerophagia, dryness, and mask intolerance.
- Burden of daily reporting.
- Use of validated patient-reported outcome instruments.
- Handling of delayed outcomes and inconsistent reporting.
- Which confounders must be recorded.

### F14.6 OSCAR integration

- Which OSCAR 2 versions will be supported initially?
- What external database/API contract is sufficiently stable?
- Will the OSCAR project accept a headless importer?
- Who will maintain the upstream contribution?
- What happens during OSCAR schema upgrades?
- How should the app behave when OSCAR is open?
- Can OSCAR provide a supported deep link to a date and waveform timestamp?
- How will GPL obligations affect distribution?

### F14.7 Engine implementation

- Rust-only production engine or mixed Rust/Python deployment?
- Stable serialization format for the engine API.
- Local database choice.
- Precision, downsampling, and waveform-retention policies.
- Plug-in mechanism for new metrics.
- Reproducibility across platforms and CPU architectures.
- Whether third-party researchers may supply analysis modules.

### F14.8 Workspace and cloud

- Default storage mode: local only, synchronized results, or synchronized raw data?
- Which cloud-folder providers are supported at launch?
- Folder-based synchronization versus an application-managed service.
- End-to-end encryption and key recovery.
- Metadata visible to storage providers.
- Multi-device conflict policy.
- Backup, restore, export, and deletion semantics.
- Maximum storage size and retention period.
- Whether a remote MCP service can operate on normalized data without raw waveforms.

### F14.9 AI and MCP

- Which MCP tools are included in version 1?
- Local MCP only initially, or remote MCP at launch?
- Authentication and OAuth design.
- Per-tool permission model.
- Which external AI clients will be tested and officially supported?
- How built-in AI credentials are stored.
- Whether model prompts and answers synchronize by default.
- What constitutes sufficient evidence for an AI-generated statement?
- Whether arbitrary correlation requests are allowed and how multiple-comparison risk is explained.
- How local models with weaker reasoning are qualified.
- Whether AI may draft settings experiments in the first release.

### F14.10 Privacy and security

- Threat model and data classification.
- Encryption at rest and in transit.
- Device authentication and revocation.
- Cloud-folder compromise and malicious-file handling.
- MCP prompt injection and tool abuse defenses.
- Redaction for exported consultation packages.
- Audit-log retention.
- Crash and telemetry policy.
- Vulnerability disclosure and security-update process.
- Whether any analytics are permitted and, if so, their consent model.

### F14.11 Clinical, regulatory, and liability

- Intended-use statement.
- Regulatory classification in target markets.
- Required quality system and documentation.
- Clinical evidence required before public recommendations.
- Appropriate clinician specialties for review.
- Contraindication and escalation policy ownership.
- Adverse-event reporting process.
- Liability allocation among the product, AI provider, user, and clinician.
- Language that is educational versus prescriptive.
- Whether the product can launch first in a non-recommendation research mode.

### F14.12 Licensing and governance

- Open-source status of the engine, MCP server, applications, and OSCAR helper.
- Compatibility with OSCAR's GPLv3 license.
- Whether a commercial layer can remain separate from GPL components.
- Contributor agreement and governance.
- Ownership and licensing of user-contributed anonymized data.
- Use of published algorithms and reference implementations.

### F14.13 Business and operations

- Free, paid, subscription, donation-supported, or hybrid model.
- Which features, if any, may be paid without undermining access.
- Cost responsibility for hosted AI and remote MCP.
- Support expectations for a health-related product.
- Insurance or clinician reimbursement opportunities.
- Hosting and compliance costs.
- Community moderation and misuse handling.

### F14.14 Product name and identity

- Final name and tagline.
- Trademark and domain clearance.
- Balance of humor and clinical credibility.
- Whether the fighter-pilot theme appears only in marketing or also in the interface.
- Avoidance of protected entertainment characters and phrases.

---

## F15. Major risks

| Risk | Consequence | Proposed mitigation |
|---|---|---|
| Incorrect settings recommendation | User harm | Narrow scope, deterministic rules, expert review, stop criteria, confirmation, regulated-development assessment |
| OSCAR schema or loader changes | Broken import | Versioned adapter, compatibility tests, upstream collaboration |
| No headless OSCAR importer | Manual friction | Upstream contribution; manual OSCAR import as temporary fallback |
| AI hallucination | Misleading explanation | Tool-grounded claims, evidence links, fixed safety layer, no direct activation |
| Cloud conflict or corruption | Lost experiment state | Append-only events, hashes, atomic writes, backups, recovery |
| Privacy breach | Exposure of health data | Local-first defaults, minimal synchronization, encryption, revocation, threat modeling |
| Regulatory misclassification | Delayed or prohibited launch | Early specialist assessment before building recommendation features |
| Overfitting to one user's data | Poor generalization | Diverse fixtures, external review, personalized baselines, cohort validation |
| False causal conclusions | Ineffective or harmful experiments | Single-variable protocol, adequate duration, confounder logging, inconclusive state |
| GPL incompatibility | Distribution constraints | Early licensing review, clean adapter boundary, upstream contribution |
| User burden | Missing subjective data | Very short daily logs, reminders, sensible defaults |
| Mobile platform limitations | Inconsistent synchronization or MCP | Remote authenticated service, native storage plugins, universal export fallback |

---

## F16. Questions for reviewers

### Clinical reviewers

1. Is the proposed closed-loop experiment model clinically defensible?
2. Which settings are appropriate or inappropriate for user-directed experiments?
3. What safety exclusions and stop rules are missing?
4. Which objective and subjective outcomes should determine success?
5. How should ASV-specific risks and contraindications be screened?
6. What evidence would be required before recommendations are released?

### OSCAR maintainers and PAP-data experts

1. Is a supported headless import interface feasible and desirable?
2. What is the intended external contract for OSCAR 2 data access?
3. How should a read-only adapter obtain a consistent snapshot?
4. Can findings deep-link into OSCAR at a date and timestamp?
5. What GPL and maintenance concerns should shape the architecture?

### Software architects

1. Are the engine, adapter, MCP, synchronization, and GUI boundaries appropriate?
2. Is Tauri 2 suitable for the intended desktop and mobile targets?
3. Should the production engine be Rust, Python, or a carefully bounded combination?
4. What event and synchronization model best supports cloud folders and offline use?
5. What architectural choices would be expensive to reverse later?

### AI and MCP reviewers

1. Are the proposed tools sufficiently powerful for unforeseen questions without exposing arbitrary code or data access?
2. Is MCP the correct common boundary for built-in and external AI?
3. What transport, authentication, and approval model should remote MCP use?
4. How should tool-call evidence and external conversation insights be persisted?
5. How should model capability differences be communicated?

### Privacy and security reviewers

1. What should remain local by default?
2. Can provider-neutral cloud-folder synchronization be made reliable and secure?
3. What data-minimization rules should apply to AI tools?
4. What are the highest-risk attack paths involving MCP, imported data, and cloud state?
5. What security assurance is expected before health data is synchronized?

### Regulatory and legal reviewers

1. Does recommending PAP settings make the product regulated software in the target market?
2. What intended-use language and evidence would be required?
3. What claims must be avoided before clearance or approval?
4. How do OSCAR's GPLv3 license and a possible headless-import contribution affect distribution?
5. What naming and marketing language creates avoidable intellectual-property risk?

---

## F17. Recommended future-product next steps

No work toward public distribution of the future product should begin until the following are completed:

1. Circulate this document to at least one PAP/ASV clinical expert, one OSCAR maintainer or data expert, one software architect, and one regulatory specialist.
2. Resolve the initial population, allowed recommendation scope, and jurisdiction.
3. Confirm the technical feasibility and intended contract for reading OSCAR 2 data.
4. Discuss an upstream headless importer with OSCAR maintainers.
5. Define the first experiment protocol in precise, testable terms.
6. Define the normalized data and provenance schema.
7. Establish initial safety exclusions, stop conditions, and escalation rules.
8. Decide the local/cloud storage modes and threat model.
9. Decide the open-source and GPL strategy.
10. Convert approved requirements into an architecture decision record and milestone backlog.

---

## F18. Review outcome template

Reviewers may use the following structure:

```text
Reviewer role:
Date:

Overall assessment:

Decisions supported:

Decisions that should be reopened:

Missing requirements:

Highest safety concern:

Highest technical risk:

Highest product risk:

Recommended changes before development:

Recommended first prototype:

Go / revise / stop recommendation:
```

---

## F19. Reference points reviewed during concept development

- OSCAR official site and OSCAR 2 release information: https://www.sleepfiles.com/OSCAR/
- AirwayLab product and methodology overview: https://airwaylab.app/
- AirwayLab open-source repository: https://github.com/airwaylab-app/airwaylab
- Tauri 2 documentation: https://v2.tauri.app/
- OpenAI MCP and tool documentation: https://developers.openai.com/
- Anthropic remote MCP connector documentation: https://support.anthropic.com/en/articles/11503834-building-custom-integrations-via-remote-mcp-servers
- ResMed AirCurve ASV user guide and contraindication information: https://document.resmed.com/documents/products/machine/aircurve-series/user-guide/aircurve-10-cs-pacewave_user-guide_apac_eng.pdf

These references inform feasibility and terminology. They do not constitute clinical, regulatory, licensing, or legal approval of the proposed product.
