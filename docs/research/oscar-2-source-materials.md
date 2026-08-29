# OSCAR 2 source-material provenance

**Retrieved:** August 28, 2026 (America/Denver)

**Release context:** OSCAR 2.0.1, released June 23, 2026

**Scope:** Source-material identification only; no OSCAR database was opened,
no schema was reverse engineered, and no bundled code was run.

## Official source chain

The [official OSCAR download page](https://www.sleepfiles.com/OSCAR/) identifies
the current release as OSCAR 2.0.1 and links **OSCAR 2.0 SQL Notes** to this
release-specific archive:

- [OSCAR 2.0.1 Notes.zip](https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip)

The same release page describes OSCAR 2.0 as including a demo program and
specifications for reading OSCAR data with Python. The archive contains both
the SQL documentation collection and that Python demonstrator.

Archive verification at retrieval:

| Field | Observed value |
|---|---|
| URL | `https://www.sleepfiles.com/OSCAR/2.0.1/Notes.zip` |
| HTTP `Last-Modified` | `Tue, 23 Jun 2026 16:42:55 GMT` |
| Content length | 847,895 bytes |
| SHA-256 | `b5ef2878d73175b62e29a9fce8373de0e697c234130528005c3d32e3d6399ef8` |
| ZIP member timestamp | `2026-06-17 07:00` as stored by the archive; timezone unspecified |

The release-specific URL establishes the OSCAR 2.0.1 distribution context.
The checksum is the immutable identifier for the exact archive inspected,
because the server could replace content at the same URL later.

## OSCAR 2 SQL Notes

**Artifact:** the `Notes.zip` documentation collection linked as **OSCAR 2.0
SQL Notes** from the official download page. It is a directory of notes rather
than one document. Database material is under `Notes/Database/`, including:

- `DATABASE_SCHEMA.md`
- `DATABASE_SCHEMA_REFERENCE.md`
- `DATA_DICTIONARY.md`
- `HOW_TO_USE_QUERIES.md`
- `QUERY_RECENT_SESSION_SETTINGS.sql`
- `USEFUL_QUERIES.sql`

**Version evidence:** the archive is distributed for OSCAR 2.0.1. Both
`DATABASE_SCHEMA.md` and `DATABASE_SCHEMA_REFERENCE.md` identify themselves as
**Schema Version 16**, last updated **2026 Q2**. No separate semantic version
for the SQL Notes collection is stated inside the archive.

## Official Python demonstration

The official archive contains this demonstrator and its specification:

| Role | Exact archive path | Embedded version evidence | SHA-256 |
|---|---|---|---|
| Demonstrator | `Notes/Waveform Demo/oscar_waveform_demo.py` | No script release number; `SUPPORTED_SCHEMA_VERSION = 13` | `835b9306f57e22372d4e79b709d1fb71846cbe91bee4ec41cbdcb8e8d247e2ad` |
| Specification | `Notes/Waveform Demo/python_waveform_demo_spec.md` | Status `Draft`; dated `2026-04-14`; asserts schema v13 | `642229e105b2eca51491bc70e0d0a623fb0c2e23205224aacc4e7d427cdbae3e` |

Byte-identical copies of both files also appear under
`Notes/Accessing OSCAR Data/`. The exact Python artifact inspected is therefore
the copy in `Notes/Waveform Demo/`, with the matching copy providing an archive
consistency check.

**Version interpretation:** the Python files are part of the official OSCAR
2.0.1 Notes distribution, but neither file labels itself version 2.0.1. Their
most specific internal identifiers are the specification date/status and the
schema-v13 assertion above; they must not be described as a schema-v16 demo.

## Follow-up boundary

Both required artifacts are available. The bundled SQL documentation targets
schema v16 while the demonstrator targets schema v13. This is recorded as a
compatibility question for the later database-inventory and demonstration
sprints; S03 does not inspect a database, reconcile schemas, modify the demo,
or design an adapter.

The downloaded verification copy was kept only in a disposable `/tmp`
directory and is not part of the repository.
