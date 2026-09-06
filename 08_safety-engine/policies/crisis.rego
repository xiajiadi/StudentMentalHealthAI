package student_mental_health_ai.safety

import rego.v1

explicit_crisis_signal_ids := [
signal.signal_id |
	signal := input.signals[_]
	signal.reason_code == "EXPLICIT_CRISIS_SIGNAL"
]

has_explicit_crisis if {
	count(explicit_crisis_signal_ids) > 0
}
