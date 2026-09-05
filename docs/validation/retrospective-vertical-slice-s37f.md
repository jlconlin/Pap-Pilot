# S37F retrospective vertical-slice validation

**Date:** September 4, 2026
**Scope:** Connect the existing selected-cohort, persisted-history, deterministic-evaluation, report, API, and browser layers; then re-run the Milestone 3 and 4 gates through the installed localhost application.
**Decision:** Milestones 3 and 4 pass for the personal retrospective prototype. This decision demonstrates a complete evidence-linked product path; the synthetic result is not evidence about the user's therapy and does not authorize prospective, remote, AI, clinical, or device-control behavior.

## Safety and data boundary

The validation used a fresh wholly synthetic schema-17 OSCAR database containing six selected sessions on six nights and a temporary PAP Pilot experiment database populated through the accepted S37B and S37C intake operations. The OSCAR file was made read-only and the versioned workspace configuration explicitly asserted that it was a fixed disposable copy made with OSCAR closed. The configured loader used the guarded adapter with `trusted_immutable_copy=True`; SHA-256 before the first launch and after the corrected-history restart remained `4b18ce41e8d3dca953d08a8445e16680185b9173070734219345f511b9b03ce5`. No live or private OSCAR data, local PAP Pilot history, therapy date, identifier, waveform, journal response, or credential was accessed or retained. The temporary configuration and both databases were removed after the server stopped.

## Connected path

The version-1 `pap-pilot.retrospective-workspace` configuration names an existing fixed OSCAR copy, an existing `pap_pilot.sqlite3`, every selected `sessions.id`, and one explicit bounded representative interval per arm. Paths resolve relative to the configuration file. Startup refuses a missing disposable-copy assertion, missing files, malformed or extra fields, nonunique session identifiers, incomplete or reordered arm selections, unselected interval sessions, and every invalid downstream adapter, replay, evaluation, or report contract rather than choosing or inventing a substitute.

The installed command loads exactly those sessions through `extract_normalized_oscar_cohort`, replays the effective append-only experiment and retrospective user evidence, runs the existing S37D deterministic evaluation, constructs the existing S37E evaluated report, freezes its canonical JSON for the API, and points the history route at the same persisted database. No analysis or threshold is implemented in the API or UI.

The protected run produced three included baseline nights and three included intervention nights, two calculated objective outcomes, four available structured subjective outcomes, available quality/confounder/adverse-effect inventories, and the deterministic synthetic classification `clear_improvement` with action `keep`. The report provenance included all six selected OSCAR session-row identifiers. Both explicit interval cards were available; Flow Rate and Mask Pressure supplied four rendered SVG traces in total, while each interval's sparse Leak input had only one stored update inside the 200 ms half-open window and therefore remained visibly missing with no inferred trace.

The served history initially contained eleven effective and retained events. The bounded correction API appended a corrected boundary and its linked note, producing thirteen retained events without replacing the earlier boundary. After clean server shutdown and a new installed-command process, replay returned the thirteen-event history, the corrected application time `1800259199000`, the retained note, and a newly rebuilt evaluated report. The correction builder now carries forward the corrected boundary's cohort and source provenance, so the deterministic engine can validate the effective protocol after restart.

## Vertical-slice result

| Plan step | Evidence | Result |
|---|---|---|
| 1. Read relevant nights and settings | The explicit six-session selection was extracted from one protected schema-17 OSCAR copy in one guarded read transaction; normalized settings retained PS Min 2 for the first three nights and PS Min 1 for the last three. | Pass |
| 2. Detect or confirm the settings-change boundary | The persisted S37B history contained the exact user-confirmed boundary; neither the loader nor UI inferred it from the observed settings transition. | Pass |
| 3. Assign nights to periods | Corrected-wall-clock allocation included three baseline and three intervention nights. | Pass |
| 4. Apply quality criteria | Structural and signal quality ran for every selected night, and the report retained the quality inventory and source links. | Pass |
| 5. Calculate objective outcomes | Both version-1 PAP Pilot metrics were calculated independently from normalized Flow Rate, Mask Pressure, and Leak evidence for every included night. | Pass |
| 6. Incorporate journal and confounders where available | Exact S37C manifests and structured synthetic journals replayed for all six nights; explicit none-reported confounder/adverse states remained attributable and were not inferred from absence. | Pass |
| 7. Show representative waveform segments | The two caller-selected raw-relative windows rendered four bounded source traces; insufficient sparse Leak excerpts stayed visibly missing. | Pass |
| 8. Produce an evidence-linked evaluation | The schema-version-2 evaluated report linked the cohort, every metric and quality result, effective user events, both selections, and the complete source inventory. | Pass |
| 9. Determine classification and action | The unchanged rule-set produced the reproducible synthetic `clear_improvement` / `keep` result without AI. | Pass |
| 10. Display the complete experiment in the UI | The installed localhost UI rendered all nine required report sections, every metric/evidence label, the issued result, explicit no-required-inputs state, both interval cards, the complete history, and the bounded correction form. | Pass |

## Milestone decisions

### Milestone 3 — pass

The engine now demonstrably produces a reproducible evidence-linked retrospective evaluation without AI from selected OSCAR records and effective persisted history. The source and installed suites independently reconstruct the same complete pipeline, and the protected run proves that the configured product startup—not a test-only injected report—performs the composition. The result includes the experiment/event schemas, baseline/intervention allocation, both initial metrics, all available user evidence, the version-1 classifier, deterministic provenance, explicit limitations, and honest missing states.

### Milestone 4 — pass

The PS Min experiment can now be reviewed from beginning to end through the installed local web application. It shows experiment status, both periods, objective and subjective outcomes, quality/confounder/adverse evidence, representative waveforms, missing signal evidence, final classification/action, uncertainty, limitations, source links, full append-only history, and the bounded correction surface. The service remained fixed to numeric loopback `127.0.0.1:8765`; an applied-boundary correction and note survived process restart without erasing the corrected event, and startup rebuilt the report from the corrected effective history.

## Validation performed

- Ran `PYTHONPATH=src .venv/bin/python -B -W error::ResourceWarning -m unittest tests.test_retrospective_local_workspace tests.test_boundary_corrections tests.test_local_api tests.test_overview_ui -q`; all twenty-eight focused workspace/correction/API/UI tests passed.
- Ran `PYTHONPATH=src .venv/bin/python -B -W error::ResourceWarning -m unittest discover -s tests -q`; all two hundred sixty-eight source-tree tests passed.
- Rebuilt and installed the wheel with `.venv/bin/python -m pip install --force-reinstall --no-deps --no-build-isolation .`, then ran `.venv/bin/python -B -W error::ResourceWarning -m unittest discover -s tests -q`; all two hundred sixty-eight tests passed against the installed package.
- Started the installed `.venv/bin/pap-pilot-api --workspace-config /tmp/.../pap-pilot-workspace.json`, requested health, overview, packaged JavaScript, summary, and history over the real `127.0.0.1:8765` socket, ran the packaged JavaScript renderers against the responses, appended one synthetic boundary correction and note, shut down cleanly, restarted the installed command, and repeated the report/history/render checks. The final sanitized result was thirteen retained history events, the corrected effective boundary, nine required report sections, four waveform SVGs, two honest missing-signal panels, `clear_improvement`, `keep`, and an unchanged OSCAR-copy digest.
- Confirmed that the temporary server stopped and the disposable validation directory was removed. `Plan.md` did not change because S37F completes existing milestone gates without changing product scope, safety boundaries, architecture, or requirements.

## Scope boundary

The default no-configuration view remains the immutable S31/S32 missing-evidence fixture. S37F does not add automatic cohort or interval selection, general editing, new metrics or thresholds, prospective workflow, remote binding, AI, clinical interpretation, device-setting instructions, or OSCAR writes. A real retrospective result still requires the known user to supply exact attributable local protocol and historical evidence through the accepted bounded intake before configuring the app; absent evidence must remain explicit.
