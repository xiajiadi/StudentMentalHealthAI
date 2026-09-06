# LLM Runtime Backend Integration Request

Status: OPEN — no formal LLM Runtime HTTP service was found in Round 1.

## Evidence

The inspected 06_llm-runtime module exposes RuntimeService and provider ports,
including the internal Ollama provider path. It does not publish a formal
application HTTP surface. Backend therefore uses LLMRuntimeClient plus
ContractFakeLLMRuntimeClient, labelled CONTRACT_FAKE, and never calls Ollama
directly.

## Requested future surface

The LLM Runtime owner should publish an internal generation endpoint accepting
the approved prompt reference, retrieval reference, model policy, language,
trace correlation, and an idempotency key. It should return a versioned,
structured candidate plus model/runtime provenance, with bounded output and
explicit timeout/unavailable/invalid-response errors.

Backend will send candidates to Safety before publication and will keep student
output buffered. Streaming requires a separately accepted streamed Safety
contract and is deferred. No LLM Runtime files were modified by Backend Round
1.
