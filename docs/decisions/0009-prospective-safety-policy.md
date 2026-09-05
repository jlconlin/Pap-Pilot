# Decision 0009: Initial prospective safety policy

**Decision ID:** `pap-pilot.prospective-safety-policy`
**Version:** 1
**Status:** Accepted
**Date:** 2026-09-04

## Decision

The prototype may support one manually applied, single-variable prospective trial: PS Min 2.0 to 1.0 cm H₂O while fixed-EPAP ASV mode and every other setting remain unchanged. This is an engineering eligibility and evidence policy, not a clinical safety claim or treatment recommendation. PAP Pilot never writes OSCAR or device data, starts or stops therapy, connects remotely, or asks an AI service to choose or apply a setting.

## Allowlist and bounds

- The only changeable primary variable is `PSMin`; the required proposal is exactly `2.0 → 1.0 cm H₂O`.
- The settings signature must remain fixed-EPAP ASV: `therapy_mode_code=6`, `loader_mode_code=7`, with `EPAP`, `PSMax`, and `MaxIPAP` held fixed.
- Values must be finite numeric cm H₂O values and satisfy `0 ≤ PSMin ≤ PSMax` and `EPAP + PSMax = MaxIPAP`. The policy does not infer or expand a device's permissible range.
- One proposal changes one variable once. Mode changes, compound changes, repeated stacking, and any other setting are unsupported and blocked.

## Required evidence before and during a trial

- A complete pre-change six-setting snapshot, selected profile/machine identity, proposal, explicit user acceptance, manual-application timestamp, and named prior setting are required. Unknown prior settings block the proposal.
- Each arm needs at least three included nights (or the proposal's larger requested minimum). Each included night needs the required Flow Rate, Mask Pressure, and Leak provenance and at least 300,000 ms of usable data for each selected objective metric. The fixed mode/device/settings identity must be consistent; unresolved time drift, schema/source mismatch, malformed boundaries, or missing required evidence blocks eligibility.
- Intervention journals are optional inputs, but missing reports are unknown and never favorable. Confounded or excluded nights remain retained and labeled. No result is issued from fabricated, inferred, or silently discarded evidence.

## Exclusions

PAP Pilot blocks proposals involving mode/profile/machine changes, EPAP/PSMax/MaxIPAP changes, start/stop instructions, remote control, direct OSCAR writes, unsupported schemas or sources, concurrent mask/equipment/medication changes presented as the intervention, or missing acceptance, application confirmation, baseline snapshot, stop rule, or reversion target. Clinical diagnosis, normalization, and causal claims are outside scope.

## Stop and escalation rules

There is no automatic stop or device action. The user must stop the trial and manually revert if any of the following occurs: a material adverse effect reported by the user; a clinician instructs stopping; the applied setting, mode, device, or held-fixed value does not match the proposal; or source integrity/time-boundary evidence becomes unresolved. Urgent symptoms require appropriate clinical care rather than an app decision.

As a conservative engineering sentinel, a trial also enters `stop_review` when two consecutive otherwise-eligible intervention nights show an adverse-direction result against the baseline median in any accepted S31/S32 metric or structured journal domain at the S32 thresholds (for example ventilation ratio ≥1.30, awakenings ≥1, sleep quality or morning energy ≤−1, or tiredness ≥+1). These are review triggers, not clinical cutoffs; one adverse night is sufficient when accompanied by a material user-reported effect. Insufficient data pauses evaluation and cannot justify keeping the change.

## Reversion requirements

The proposal must preserve the exact prior snapshot and target value. On any stop trigger, user request, or clinician instruction, the user manually restores that snapshot outside PAP Pilot. The application may display the instruction and record an event, but it cannot perform or verify the device change. A reversion event records timestamp, actor, reason, and exact prior settings append-only; if the prior snapshot is unavailable, the policy blocks the trial. Keep/extend decisions require the minimum arm evidence and a new explicit review; otherwise the state remains paused or inconclusive.

## Enforcement and versioning boundary

Every prospective evaluation records this policy ID and version. S39 may implement only these deterministic checks and structured failure states; S40 may record lifecycle events but may not add device control. Any change to the allowlist, bounds, evidence minimums, stop rules, or reversion contract requires a new policy version and decision record. AI output, if considered in a later sprint, cannot bypass a failed gate, and hosted health-data transmission requires a separate explicit decision.

