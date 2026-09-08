# Structured Output Product Compatibility Technical Decision V1

Status: **FROZEN**

This decision freezes the scope and acceptance boundary for Structured Output
Product Compatibility Closure Round 1. It does not change the public
`generation.v1` contract.

## SOC-01

This Closure fixes only the reproducible product structured-output compatibility
bug blocking Normal product completion.

## SOC-02

Formal baseline remains Runtime accepted commit
`2972be77e537ef03033332039a6ed0eed8e451ef` plus the preserved GPI partial
evidence checkpoint.

## SOC-03

Accepted synthetic RAG publication identity and hash MUST remain unchanged.

## SOC-04

D2 corpus MUST NOT be used.

## SOC-05

Formal primary model identity and digest MUST remain unchanged.

## SOC-06

Ollama remains version 0.33.3.

## SOC-07

Context remains 8192, KV f16, parallel 1.

## SOC-08

`generation.v1` externally visible semantics MUST remain unchanged.

## SOC-09

RAG retrieval algorithm, BGE-M3, BM25S, RRF and reranker policy MUST remain
unchanged.

## SOC-10

No structured-output bypass is allowed.

## SOC-11

No generic regex repair is allowed.

## SOC-12

No "extract the first {...}" heuristic is allowed.

## SOC-13

No blind retry-until-valid loop is allowed.

## SOC-14

No acceptance of malformed JSON is allowed.

## SOC-15

No schema weakening merely to pass the model is allowed.

## SOC-16

No replacement of exact accepted RAG identities with fake neutral identities in
final acceptance flows is allowed.

## SOC-17

Diagnostic prompt mutations are allowed only in isolated diagnosis cases and
must NEVER be labelled product acceptance.

## SOC-18

A product fix may modify only the proven owning module(s).

## SOC-19

RAG, Safety, CAT, Database, Frontend and Frozen Root are outside engineering
scope.

## SOC-20

If the bug requires a breaking root contract or `generation.v1` change, STOP and
return `CONTROLLER_DECISION_REQUIRED`.

## SOC-21

If exact provenance identifiers are the proven trigger, a reversible LLM-facing
citation projection MAY be considered only if exact external provenance identity
is preserved deterministically outside the model.

## SOC-22

Any citation alias/projection MUST round-trip exactly to original source/chunk
identity and MUST NOT alter RAG source identity.

## SOC-23

Raw Ollama output must remain buffered before product delivery.

## SOC-24

Real Output Safety remains mandatory after successful generation.

## SOC-25

Cloud fallback remains false.

## SOC-26

No real student data may be used.

## SOC-27

Raw synthetic diagnostic payloads, if required, stay local-only and are not
committed.

## SOC-28

The fix must have a minimized reproducer proving before=FAIL and after=PASS.

## SOC-29

Normal product acceptance requires 3/3 full-real completion after the fix.

## SOC-30

Agent has no authority to declare ACCEPTED, merge, push, or create accepted tags.
