package student_mental_health_ai.safety

import rego.v1

default decision := {
	"action": "BLOCK",
	"reason_codes": ["POLICY_EVALUATION_FAILED"],
	"requires_human": true,
}

crisis_decision := {
	"action": "CRISIS_ROUTE",
	"reason_codes": ["EXPLICIT_CRISIS_SIGNAL"],
	"requires_human": true,
} if {
	has_explicit_crisis
}

component_failure_decision := {
	"action": "REVIEW_REQUIRED",
	"reason_codes": ["COMPONENT_UNAVAILABLE"],
	"requires_human": true,
} if {
	has_component_failure
}

unsafe_decision := {
	"action": "BLOCK",
	"reason_codes": ["CONTENT_UNSAFE"],
	"requires_human": false,
} if {
	count(unsafe_signal_ids) > 0
}

clinical_decision := {
	"action": "REVIEW_REQUIRED",
	"reason_codes": ["CLINICAL_OVERREACH"],
	"requires_human": true,
} if {
	count(clinical_signal_ids) > 0
}

disclosure_decision := {
	"action": "REVIEW_REQUIRED",
	"reason_codes": ["DISCLOSURE_RESTRICTED"],
	"requires_human": true,
} if {
	count(disclosure_signal_ids) > 0
}

controversial_decision := {
	"action": "REVIEW_REQUIRED",
	"reason_codes": ["CONTENT_CONTROVERSIAL"],
	"requires_human": true,
} if {
	count(controversial_signal_ids) > 0
}

privacy_decision := {
	"action": "PROCEED_WITH_BOUNDARY",
	"reason_codes": ["PII_DETECTED"],
	"requires_human": false,
} if {
	has_pii
}

normal_decision := {
	"action": "PROCEED",
	"reason_codes": ["NO_BLOCKING_SIGNAL"],
	"requires_human": false,
}

decision := crisis_decision if {
	has_explicit_crisis
} else := component_failure_decision if {
	has_component_failure
} else := unsafe_decision if {
	count(unsafe_signal_ids) > 0
} else := clinical_decision if {
	count(clinical_signal_ids) > 0
} else := disclosure_decision if {
	count(disclosure_signal_ids) > 0
} else := privacy_decision if {
	has_pii
} else := controversial_decision if {
	count(controversial_signal_ids) > 0
} else := normal_decision
