# PAP Optimization Companion repository instructions

## Governing documents

- `PAP_Optimization_Plan_v2.1.md` governs the personal prototype.
- `PAP_Optimization_Product_Plan.md` is future-product reference only.
- `PAP_Optimization_Plan_v2.md` is superseded.
- `SPRINTS.md` is the ordered implementation queue.
- `STATUS.md` is the handoff record for the next session.

## Working method

1. Read this file, the governing plan, `SPRINTS.md`, and `STATUS.md` before changing code.
2. Work on exactly one sprint at a time unless the user explicitly changes scope.
3. Do not begin the next sprint after finishing the current one.
4. Keep the sprint's exclusions intact. Record newly discovered work in `STATUS.md` instead of silently expanding scope.
5. Use a backup or disposable OSCAR database until read-only behavior is verified. Never write to the live OSCAR database.
6. Keep deterministic data, metrics, safety, and experiment logic independent from UI and AI code.
7. Add or update focused tests for each implementation sprint and run the narrowest relevant validation.
8. At the end of every sprint:
   - update its status in `SPRINTS.md`;
   - update `STATUS.md` with changes, validation, decisions, blockers, and the next sprint;
   - leave the repository in a resumable state.

## Sprint statuses

- `queued`: not started.
- `active`: the only sprint currently in progress.
- `blocked`: cannot proceed without a named input or decision.
- `done`: its stated completion check has passed.

## Safety boundaries

- The application is for one known user during the prototype phase.
- OSCAR remains the importer and canonical PAP-data store.
- OSCAR access is strictly read-only, with OSCAR closed until concurrent-read safety is investigated.
- The application never changes PAP-device settings.
- AI output is advisory and cannot override deterministic calculations or safety gates.
- Health-data transmission to a hosted AI service requires an explicit recorded decision first.

