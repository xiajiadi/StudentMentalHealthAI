from database_layer.seed import REFERENCE_ROLE_CODES


def test_reference_roles_include_a_distinct_psychological_specialist() -> None:
    assert "psychological_specialist" in REFERENCE_ROLE_CODES
    assert "reviewer" in REFERENCE_ROLE_CODES
