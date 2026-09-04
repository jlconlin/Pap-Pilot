# 0007 — Retrospective user-evidence intake

**Status:** Accepted

**Date:** September 3, 2026

**Schema identifier:** `pap-pilot.retrospective-user-evidence`

**Schema version:** 1

## Context

The selected retrospective cohort can contain historical journal responses, confounders, and adverse-effect reports, but absence of a retained response does not establish that nothing happened. The intake therefore needs an explicit per-night evidence manifest in addition to the existing version-1 journal records and append-only experiment events.

## Decision

Every selected cohort night receives exactly one immutable retrospective evidence manifest, even when no journal or observation event is available. A complete intake covers every selected night and no outside night, is ordered by the deterministic cohort order, requires an already accepted protocol and user-confirmed boundary linked to that cohort, and is appended only once by this bounded path.

Each evidence domain uses one of four explicit states:

| State | Meaning |
|---|---|
| `unavailable` | The historical source cannot establish whether the information was reported. |
| `not_reported` | It is known that the question or value was not reported. |
| `none_reported` | The user explicitly reported that no confounder or adverse effect applied. |
| `reported` | Exact attributable evidence is present. |

The journal domain uses `unavailable`, `not_reported`, or `reported`; `none_reported` is not meaningful for a journal as a whole. A reported journal retains the existing `SleepJournalEntry` unchanged, including null structured outcomes and exact original whitespace and line breaks. Confounder status agrees with the structured journal answer and any separate exact confounder observations. Reported adverse-effect status requires at least one exact adverse-effect observation. No prose is parsed or promoted into another field.

Reported journal entries continue to use the protected journal table and `sleep_journal_entry_recorded` events. Standalone confounders and adverse effects use the existing typed observation events. Store schema version 3 adds an append-only retrospective manifest table that links those exact records and events while preserving status-only nights. The journal rows, observation events, and manifests are validated and committed in one transaction or none are committed. Replay returns the complete effective per-night manifests with the exact embedded journal and observation records.

## Exclusions

This decision does not add a form, API endpoint, reminder, prospective workflow, correction or general editing path, NLP or AI interpretation, evaluation, report assembly, clinical advice, device-setting behavior, or OSCAR write.
