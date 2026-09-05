# Evaluated retrospective evidence report v2

## Purpose

This fixture freezes the schema-version-2 report produced from the wholly synthetic six-night S37D evaluation bundle and two explicitly supplied raw-relative waveform selections. It verifies the report seam without selecting intervals automatically, querying OSCAR, changing analytical rules, or involving the UI or AI.

## Retained snapshot

`tests/fixtures/evaluated-retrospective-evidence-report-v2.json` is a human-reviewable projection of every required report section plus the SHA-256 digest and deterministic record identifier of the complete canonical JSON report. The full canonical report remains reproducible from the synthetic test builder; retaining the compact projection avoids duplicating its large provenance inventory while still detecting any serialized-content change.

The populated case contains three baseline nights, three intervention nights, both version-1 objective outcomes, all four structured journal outcomes, quality and explicit no-confounder/no-adverse-effect evidence, an issued deterministic classification and action, limitations, and one 200 ms caller-selected waveform interval from each arm. Each interval requests Flow Rate, Mask Pressure, and Leak; the exact five Flow Rate and five Mask Pressure samples are retained, while the sparse Leak input is explicitly missing because that bounded window contains fewer than two stored updates.

## Missing-evidence case

The focused test also rebuilds the report after replacing every historical journal entry with an explicit `unavailable` status. All four subjective outcomes remain missing, the missing-input inventory names structured journal reports, and the already-versioned classifier result remains `inconclusive` with action `extend`. No absent answer is converted to zero, unchanged, favorable, or safe.

## Privacy and stability

Every therapy value, date, identifier, signal sample, journal response, and user source in this fixture is synthetic. No live or copied OSCAR database, local PAP Pilot database, private path, credential, or real health record is retained. Intentional changes to the report schema, source-link inventory, selection contract, or serialized output require explicit review and a new fixture version or an acknowledged snapshot update.
