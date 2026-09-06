package student_mental_health_ai.safety

import rego.v1

test_normal_proceeds if {
	decision.action == "PROCEED"
	decision.reason_codes == ["NO_BLOCKING_SIGNAL"]
		with input as {
			"actor_role": "STUDENT",
			"component_health": {"presidio": true, "nemo_guardrails": true, "qwen3guard": true},
			"signals": [],
		}
}

test_crisis_overrides_normal_assessment if {
	decision.action == "CRISIS_ROUTE"
		with input as {
			"actor_role": "STUDENT",
			"component_health": {"presidio": true, "nemo_guardrails": true, "qwen3guard": true},
			"signals": [
				{"signal_id": "assessment-1", "source": "ASSESSMENT", "reason_code": "ASSESSMENT_NORMAL"},
				{"signal_id": "crisis-1", "source": "DETERMINISTIC_RULE", "reason_code": "EXPLICIT_CRISIS_SIGNAL"},
			],
		}
}

test_component_failure_is_not_proceed if {
	decision.action == "REVIEW_REQUIRED"
		with input as {
			"actor_role": "STUDENT",
			"component_health": {"presidio": true, "nemo_guardrails": false, "qwen3guard": true},
			"signals": [],
		}
}

test_retrieval_does_not_require_generation_guards if {
	decision.action == "PROCEED"
		with input as {
			"operation": "RETRIEVAL",
			"actor_role": "STUDENT",
			"component_health": {"presidio": true, "nemo_guardrails": false, "qwen3guard": false},
			"signals": [],
		}
}

test_pii_disclosure_is_redacted if {
	requested_disclosure_policy == "REDACTED"
		with input as {
			"actor_role": "TEACHER",
			"signals": [{"signal_id": "pii-1", "source": "PRESIDIO", "reason_code": "PII_DETECTED"}],
		}
}

test_pii_gets_boundary if {
	decision.action == "PROCEED_WITH_BOUNDARY"
		with input as {
			"actor_role": "STUDENT",
			"component_health": {"presidio": true, "nemo_guardrails": true, "qwen3guard": true},
			"signals": [{"signal_id": "pii-1", "source": "PRESIDIO", "reason_code": "PII_DETECTED"}],
		}
}
