# 0002 — Normalized core records and serialization

**Status:** Accepted

**Date:** September 1, 2026

## Context

PAP Pilot needs a source-independent boundary between the read-only OSCAR adapter and later deterministic quality, metric, and experiment logic. The boundary must preserve exact source identity and units, represent both uniform waveforms and irregular updates without hiding gaps, and produce stable serialized evidence. S15 does not map adapter output, persist data, decide quality, or define derived analysis.

## Decision

The deterministic engine owns immutable version-1 records for provenance, settings, events, signal segments/signals, sessions, and nights in `pap_pilot.engine.model`. Adapter types do not cross into this package.

Every record has an explicit `record_version`; serialized records use an independently versioned `pap-pilot.normalized` envelope. Canonical JSON uses sorted object keys, compact separators, unescaped Unicode, strict finite numbers, tagged nested record types, and deterministic ordering for collections whose input order has no meaning. Deserialization rejects missing or unknown fields, duplicate JSON keys, unsupported versions or types, and invalid structural relationships.

A night contains ordered sessions. A session contains settings, events, and signals. A signal contains independent segments, retaining gaps rather than flattening them. Units and timestamp units are explicit in field names or record fields. Signal sample timestamps permit finite fractional milliseconds because OSCAR stores sample intervals as `REAL`; segment boundary closure distinguishes uniform half-open waveform ranges from inclusive timed-update ranges.

Provenance is a first-class record. It retains one or more source classifications, source system/schema/application versions, stable source-record references, source-specific values, producer identity/version, and parent-provenance identifiers. Machine-recorded data normalized by OSCAR therefore retains both origins rather than collapsing into one label.

Constructors enforce only structural invariants needed for immutable, unambiguous, serializable records. They do not assign quality, determine event completeness, apply clinical thresholds, derive metrics, exclude intervals, or decide experiment suitability.

## Consequences

- S16 must create stable normalized identifiers and map every required adapter source identifier/value into provenance without adding new OSCAR queries.
- A serialization or field-contract change that is not backward compatible requires a format or record-version change rather than silently changing version 1.
- Canonical serialization is a data interchange contract, not a persistence implementation; local storage remains undecided.
- Quality, derived-result provenance, persistence, experiment state, UI contracts, and AI records remain owned by their later sprints.
