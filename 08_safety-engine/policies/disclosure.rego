package student_mental_health_ai.safety

import rego.v1

default requested_disclosure_policy := "HIDDEN"

requested_disclosure_policy := "REDACTED" if {
	has_pii
}

requested_disclosure_policy := "SUMMARY" if {
	input.actor_role == "REVIEWER"
}

requested_disclosure_policy := "FULL" if {
	input.actor_role == "SYSTEM"
}
