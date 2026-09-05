# Decision 0010: AI data boundary and provider

**Decision ID:** `pap-pilot.ai-data-boundary-and-provider`
**Version:** 1
**Status:** Accepted with hosted transmission deferred
**Date:** 2026-09-05

## Decision

OpenAI's Responses API is the single provider candidate for a later advisory integration. No provider call, credential, or hosted health-data transmission is authorized in the personal prototype by this decision. S45 and later AI work are blocked until the user records a separate affirmative transmission consent after reviewing the exact payload and retention controls.

The official OpenAI data-controls documentation states that API content is not used to train models by default, while abuse-monitoring logs may contain customer content and are retained up to 30 days by default; endpoint application state can have additional retention. Those controls do not by themselves constitute user consent or a clinical-data authorization. See [official OpenAI data-controls documentation](https://developers.openai.com/api/docs/guides/your-data).

## Permitted payload if separately authorized

Only a newly constructed, minimal advisory context may be sent after consent: versioned aggregate metric values and units, quality/status summaries, structured journal ratings and confounder states, the bounded selected waveform excerpts already approved for display, the experiment hypothesis, and engine/rule-set/prompt versions. Every field must carry its source class and provenance reference in the local ledger before transmission.

The payload must exclude raw OSCAR databases/files, raw session identifiers, profile or machine serials, exact local dates/timestamps, filesystem paths, credentials, contact information, original free-text journal notes, unbounded waveform data, and any unsupported setting or mode. Local dates and identifiers are replaced with per-request opaque labels; values are rounded only by a versioned payload contract, never by the model.

## Redaction and minimization

- The deterministic engine constructs the payload; AI never reads OSCAR or the local database directly.
- The default payload contains no free text. A future consent record must name each optional text field explicitly; absent consent means it is omitted.
- Only one selected experiment context and the smallest bounded evidence excerpt are included. No unrelated nights, users, devices, or experiments are transmitted.
- The request is advisory and must not include an instruction to change settings, start/stop therapy, or override a deterministic gate. Returned text cannot become an authoritative metric, classification, safety decision, or device action.

## Credential and local-retention requirements

No credential is stored in the repository, experiment database, journal, browser storage, URL, or logs. A future adapter must use an operating-system credential store or an equivalent user-approved secret manager, expose only a redacted provider identifier, and fail closed when a credential is unavailable. The local ledger records provider, model, request/payload contract version, consent-record identifier, request time, response, and evidence references only after the user has authorized transmission; secrets and unredacted payloads are never logged.

## Hosted-transmission gate

Until a later explicit consent record exists, the adapter must return `hosted_transmission_not_authorized` without making a network request. Consent must identify the provider, endpoint, model, allowed fields, redaction contract, retention settings, account/project, revocation method, and whether the user accepts provider-side processing. A change in provider, endpoint, model family, payload fields, or retention posture requires renewed consent and a new decision version.

## Scope boundary

This decision selects one future provider candidate and resolves the data-minimization contract; it implements no API calls or multi-provider abstraction. Local-only deterministic analysis remains fully supported. OpenAI output, if later enabled, is advisory and cannot bypass the S39 safety gate or S40 lifecycle rules. No clinical, diagnostic, causal, or treatment claim may be generated from an AI response.

