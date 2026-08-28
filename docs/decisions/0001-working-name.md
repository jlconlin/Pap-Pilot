# Decision 0001: Working product name and identifiers

**Status:** Proposed — awaiting explicit user approval
**Date proposed:** August 28, 2026
**Decision owner:** User

## Context

The prototype needs a stable working identity before project scaffolding begins. The name should describe an evidence-oriented PAP experiment companion without implying that the application autonomously controls, configures, or medically manages a PAP device.

Final trademark, legal, domain, app-store, social-handle, logo, and visual-branding work is explicitly outside this decision.

## Criteria

The working name should:

1. Make the PAP context reasonably clear.
2. Suggest guidance, evidence, or review rather than device control.
3. Remain useful if support expands beyond one ASV machine or one AI provider.
4. Produce simple, unambiguous technical identifiers.
5. Avoid making clinical-effectiveness or autonomous-optimization claims.

## Candidate assessment

| Candidate | Strength | Concern |
| --- | --- | --- |
| PAP Compass | Clear PAP context; “Compass” communicates user-directed guidance | Generic metaphor; external clearance remains deferred |
| PAP Lab | Strong experiment framing; concise | Can sound like a clinical or testing service |
| BreathLoop | Memorable and broader than one device | Can imply closed-loop device control and does not clearly identify PAP |
| PAPwise | Friendly and advisory | “Wise” can imply authority or correctness |
| PAP Optimization Companion | Accurate description | Long; “optimization” may overstate what the prototype establishes |
| PAPilot | Memorable wordplay | “Pilot” implies autonomous control |
| FlowTune | Short and relevant to therapy data | “Tune” implies settings control |
| ServoPilot | Signals ASV relevance | Too mode-specific and strongly implies control |

## Proposed decision

Use **PAP Compass** as the working product name.

Proposed identifiers:

- Display name: `PAP Compass`
- Technical slug and command name: `pap-compass`
- Python import package: `pap_compass`
- Local application database: `pap_compass.sqlite3`

## Rationale

“PAP” anchors the product in its actual data domain. “Compass” describes advisory direction while leaving the user responsible for reviewing and manually applying any settings change. The name does not tie the implementation to ASV, OSCAR, a particular AI provider, or a future distribution model.

## Consequences if approved

- Replace the `PAP Optimization Companion` placeholder in the governing and tracking documents.
- Use the approved identifiers when the Python project and local database are created.
- Continue to describe the application as advisory; the working name does not relax any deterministic safety boundary.
- Revisit external clearance only before distribution or public branding.

## Approval

Not yet approved. S01 cannot be marked complete until the user explicitly approves this proposal or selects a replacement and its identifiers.
