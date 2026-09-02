# Reference night fixture v1

## Purpose

Reference night v1 freezes one deterministic schema-17 adapter scenario and its expected S16 normalized output. It is a mapping-regression contract only: it does not define data-quality rules, analytical metrics, clinical expectations, or experiment suitability.

## Origin and privacy

The source fixture is the database assembled by `SessionSummaryTests._create_reference_night_v1_database` in `tests/test_session_summary.py`. Every profile label, machine identifier, session identifier, date, timestamp, setting, event, waveform value, sparse update, storage value, and checksum in that database is invented test data. No row or value was copied, shifted, rounded, or otherwise transformed from the user's OSCAR database, so the fixture's safety does not depend on reversible pseudonymization of private health data.

The table and field relationships reflect the schema-17 structures established in S06–S14C. The separate private reference-night cross-check established that the adapter agrees with OSCAR for the scoped import contracts, but none of that private night's identifiers or health values is part of this retained fixture.

The synthetic database exists only in a temporary directory while the test runs. SQLite files remain excluded from version control.

## Versioned expected output

`tests/fixtures/reference-night-v1.expected.json` is the retained version-1 expectation. It records human-reviewable normalized structure plus the exact byte length and SHA-256 digest of the canonical version-1 normalized JSON envelope.

`test_reference_night_v1_matches_frozen_expected_output` rebuilds the synthetic database, performs the existing read-only extraction and pure S16 mapping, compares the readable structure, and compares the exact canonical-output digest. The test also mutates one mapped date in memory and confirms that the frozen digest rejects that intentional change.

Reference night v1 is immutable evidence. A future intentional change to its source data, mapping semantics, normalized format, or expected output requires explicit review and a new fixture version rather than silently replacing this expectation.
