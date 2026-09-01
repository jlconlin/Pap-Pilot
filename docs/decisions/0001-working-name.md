# Decision 0001: Working product name and identifiers

**Status:** Accepted
**Date proposed:** August 28, 2026
**Date accepted:** August 28, 2026
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
| PAP Compass | Clear PAP context; “Compass” communicates user-directed guidance | Generic metaphor; less memorable and playful |
| PAP Lab | Strong experiment framing; concise | Can sound like a clinical or testing service |
| BreathLoop | Memorable and broader than one device | Can imply closed-loop device control and does not clearly identify PAP |
| PAPwise | Friendly and advisory | “Wise” can imply authority or correctness |
| PAP Optimization Companion | Accurate description | Long; “optimization” may overstate what the prototype establishes |
| PAP Pilot | Memorable wordplay; supports a friendly mascot | Without the space, pronunciation is ambiguous; “pilot” can imply autonomous control |
| FlowTune | Short and relevant to therapy data | “Tune” implies settings control |
| ServoPilot | Signals ASV relevance | Too mode-specific and strongly implies control |

## Decision

Use **PAP Pilot** as the working product name, displayed as two words and pronounced “P-A-P Pilot.” The space is part of the display name and avoids the ambiguous “paw-pilot” reading of `PAPilot`.

Approved identifiers:

- Display name: `PAP Pilot`
- Technical slug and command name: `pap-pilot`
- Python import package: `pap_pilot`
- Local application database: `pap_pilot.sqlite3`

## Rationale

“PAP” anchors the product in its actual data domain. “Pilot” provides memorable wordplay and supports an approachable fighter-pilot mascot without tying the implementation to ASV, OSCAR, a particular AI provider, or a future distribution model. The application remains an advisory companion: the user reviews and manually applies every settings change, and the application never controls a PAP device. The product language and interface must not imply autonomous control.

## Consequences

- Use `PAP Pilot` consistently in governing and tracking documents.
- Preserve the space in the display name and pronounce PAP as the letters “P-A-P.”
- Use the approved technical identifiers when the Python project and local database are created.
- Continue to describe the application as advisory; the working name does not relax any deterministic safety boundary.
- Revisit external clearance only before distribution or public branding.

## Approval

The user explicitly approved the working name and complete identifier set on August 28, 2026.
