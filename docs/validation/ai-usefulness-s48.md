# AI usefulness evaluation — S48

**Date:** September 5, 2026
**Scope:** Synthetic comparison of the structured AI adapter with the deterministic PS Min retrospective fixture.
**Decision:** Revise and defer hosted AI assistance; retain the local structured contract for future authorized testing.

## Evaluation cases

| Case | Deterministic reference | AI-shaped interaction | Finding |
| --- | --- | --- | --- |
| Explain the known retrospective record | The fixture retains the PS Min 2-to-1 fact but has no attributable per-night evidence and remains `not_evaluable_without_fabrication`. | A bounded response can restate the hypothesis, expected effects, and limitations without inventing metrics. | Potential explanatory value, but no new evidence or decision value. |
| Draft a prospective change | S39 accepts only the exact PS Min 2.0-to-1.0 fixed-EPAP ASV scope with required evidence and reversion. | The same structured response attached to an out-of-scope proposal is passed through S46. | The proposal remains non-viable regardless of wording; safety control works. |
| Claim an observed improvement | The fixture has no observed per-night metrics, journal outcomes, or classification. | The response contract has no authoritative metric/classification field and cannot supply missing evidence. | Any claim of improvement is unsupported and must be rejected or labeled advisory. |
| Provider unavailable or transmission unauthorized | Decision 0010 blocks hosted transmission without explicit consent. | The adapter returns `hosted_transmission_not_authorized` before transport, or `AiProviderUnavailable` when an authorized transport is absent. | Fail-closed behavior is correct; no data leaves the machine. |

## Conclusion

The structured contract is useful for testing bounded explanation and safety routing, but this evaluation demonstrates no incremental clinical, causal, or analytical value over the deterministic engine. AI remains disabled for hosted use in the prototype. Future work may revisit it only with explicit transmission consent, a recorded payload/retention contract, provenance events, and an evaluation showing evidence-linked usefulness rather than fluent restatement. Recommendation scope is not expanded.

## Reproducibility

`tests/test_ai_usefulness.py` verifies the fixture status, the fail-closed adapter states, and the unsafe-wording safety-gate case using synthetic records only. No OSCAR database, API credential, provider call, or real health data was used.

