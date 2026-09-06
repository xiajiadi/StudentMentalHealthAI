# Internal safety contracts

These schemas are module-internal and intentionally do not replace or modify
the frozen root Contract v0.1.0. Pydantic models in
`src/safety_engine/domain/models.py` are the runtime source; these files make
the stable JSON boundary reviewable and machine-readable. The set covers
SafetyContext, SafetySignal, SafetyDecision, SafetyTrace, and HumanReviewCase.
Trace `signals` contains signal IDs only; raw prompt, assessment, and response
content is not part of this contract.
