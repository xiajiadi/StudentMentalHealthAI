package student_mental_health_ai.safety

import rego.v1

required_components := {"presidio", "nemo_guardrails", "qwen3guard"}

required_components_for_operation := {"presidio"} if {
	object.get(input, "operation", "INPUT") == "RETRIEVAL"
} else := required_components

component_failure_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.source == "SYSTEM_HEALTH"
]

missing_component_names := [
component |
	component := required_components_for_operation[_]
	object.get(input.component_health, component, false) != true
]

has_component_failure if {
	count(component_failure_ids) > 0
}

has_component_failure if {
	count(missing_component_names) > 0
}

unsafe_signal_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.reason_code in {
		"CONTENT_UNSAFE",
		"PROMPT_INJECTION",
		"JAILBREAK",
		"RETRIEVAL_SOURCE_INELIGIBLE",
	}
]

clinical_signal_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.reason_code == "CLINICAL_OVERREACH"
]

controversial_signal_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.reason_code == "CONTENT_CONTROVERSIAL"
]

privacy_signal_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.reason_code == "PII_DETECTED"
]

disclosure_signal_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.reason_code == "DISCLOSURE_RESTRICTED"
]
