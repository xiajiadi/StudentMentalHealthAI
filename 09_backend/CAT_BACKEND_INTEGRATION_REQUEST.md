# CAT Backend Integration Request

Status: OPEN — no formal CAT HTTP service was found in Round 1.

## Evidence

The inspected CAT module exposes Python-domain services and provider ports
under 01_cat-engine. The Backend did not import that runtime because the module
has its own environment and no published HTTP application. Backend Round 1
therefore uses CatClient plus ContractFakeCatClient, labelled CONTRACT_FAKE.

## Requested future surface

The CAT owner should publish a versioned internal service or an approved
cross-runtime adapter with these operations:

- start an assessment with subject_id, instrument_id, and instrument_version;
- submit one response using the CAT-owned item and response types;
- complete the session and return assessment.v1;
- report capability health and the CAT/item-bank provenance needed by
  assessment.v1.

The service must remain the authority for item selection, theta, SE, stopping
rules, and interpretation status. Backend will only transport lifecycle
commands and map the result into application DTOs.

## Compatibility and safety requirements

The surface must define timeout behavior, idempotency for start/complete,
request_id and trace_id propagation, and safe error mapping. It must not require
Backend to import CAT implementation classes or calculate psychometric values.
No CAT files were modified by Backend Round 1.
