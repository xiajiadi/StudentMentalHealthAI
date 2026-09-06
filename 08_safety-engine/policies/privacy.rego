package student_mental_health_ai.safety

import rego.v1

has_pii if {
	count(privacy_signal_ids) > 0
}
