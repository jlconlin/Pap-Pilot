# 0005 — Sleep-journal outcomes and confounders

**Status:** Accepted

**Date:** September 2, 2026

**Schema identifier:** `pap-pilot.sleep-journal`

**Schema version:** 1

## Context

The retrospective experiment needs comparable subjective outcomes without discarding the user's own description of a night. A text-only journal would preserve nuance but make deterministic comparison difficult; structured fields alone would omit unexpected context. Missing responses must also remain distinguishable from negative answers.

## Decision

Each entry is immutable, timestamped, attributable, linked to exactly one normalized therapy-night identifier, classified as user-reported, and appended atomically with a `sleep_journal_entry_recorded` experiment event. Corrections append a new entry and same-type correction event; prior text and values remain in history.

The structured morning outcomes are:

| Field | Type and scale | Meaning |
|---|---|---|
| `awakenings_count` | Nonnegative integer or null | The user's estimated number of remembered awakenings; null means not reported, not zero. |
| `sleep_quality` | Integer 1–5 or null | 1 very poor, 2 poor, 3 fair, 4 good, 5 very good. |
| `morning_energy` | Integer 1–5 or null | 1 very low, 2 low, 3 moderate, 4 high, 5 very high. |
| `daytime_tiredness` | Integer 1–5 or null | 1 not at all tired, 2 slightly tired, 3 moderately tired, 4 very tired, 5 extremely tired. |

Null always means the outcome was not reported. It is never converted to zero, a midpoint, or another inferred response.

Confounder reporting has three explicit states: `not_reported`, `none_reported`, and `reported`. A reported entry contains one or more unique categories from `travel`, `illness`, `alcohol`, `medication_change`, `unusual_sleep_schedule`, `mask_or_equipment_change`, `stress`, and `other`. A category may retain untouched user detail; `other` requires it. The initial vocabulary supports the retrospective fixture and is descriptive evidence, not a causal conclusion.

An optional `original_note` preserves the exact nonblank text, including whitespace and line breaks. Deterministic code, UI code, and AI must not silently translate that prose into structured outcomes or confounders. A user may explicitly supply both structured fields and text, even when they appear inconsistent; later evaluation must disclose rather than rewrite that evidence.

An entry must contain at least one structured outcome, an answered confounder state, or an original note. Reporter and provenance identifiers are required. The schema is versioned independently from the experiment-event and SQLite-store schemas.

## Persistence and replay

Journal records are stored in the local PAP Pilot database, never OSCAR. Store schema version 2 adds an append-only journal table and transactionally migrates an intact version-1 experiment store. Update, delete, and replacement triggers protect journal rows. The public write operation accepts the journal entry and its matching event together or commits neither.

Replay returns the complete entry history in event order and a correction-resolved effective entry sequence. The event's journal and night identifiers must exactly match the stored record, preventing dangling or cross-night references.

## Exclusions

This decision does not define a form, API endpoint, reminder, notification, NLP extraction, AI interpretation, outcome weight, meaningful-change threshold, experiment classification, or causal treatment of confounders. S29 and later work must consume these values without changing their version-1 meanings.
