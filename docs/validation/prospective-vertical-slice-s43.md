# Prospective vertical slice — S43 validation

**Date:** September 5, 2026
**Status:** Accepted for prototype Milestone 5
**Scope:** Synthetic, local-only, non-AI validation of the accepted PS Min 2.0-to-1.0 prospective policy.

## Evidence

`tests/test_prospective_vertical_slice.py` constructs three synthetic baseline nights and three synthetic intervention nights with the required 300,000 ms duration and Flow Rate, Mask Pressure, and Leak availability. The deterministic S39 gate accepts the exact fixed-EPAP ASV proposal and records policy/version identity.

The test appends the proposal, acceptance, setting-application confirmation, and keep events to a disposable `pap_pilot.sqlite3` store. S40 replay resolves the lifecycle to `kept` while retaining the append-only history. No OSCAR database or device is opened or modified.

The local API then accepts one structured morning journal entry linked to a synthetic therapy-night identifier. Replayed monitoring state reports the lifecycle, one reported night, the manual `revert` action, and `automatic_device_actions=false`; the overview renderer consumes the same bounded monitoring envelope. Journal text remains untouched and no prose interpretation occurs.

## Validation command

`PYTHONPATH=src .venv/bin/python -B -W error::ResourceWarning -m unittest tests.test_prospective_vertical_slice -v`

The synthetic run passed. The complete source-tree suite also passed with 280 tests. This demonstrates the product path through deterministic eligibility, manual lifecycle confirmation, local monitoring, journal capture, and reconstructed state; it does not establish clinical safety, therapeutic benefit, or a real-device setting change.

