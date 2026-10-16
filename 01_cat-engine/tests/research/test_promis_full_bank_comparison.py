from types import SimpleNamespace

import pytest

from cat_engine.research.promis_full_bank_comparison import (
    FullBankComparisonError,
    _independent_full_bank_eap,
)


def _symmetric_eight_item_profile():
    items = tuple(
        SimpleNamespace(
            qid=f"ITEM_{index}",
            a=1.0,
            thresholds=(-1.5, -0.5, 0.5, 1.5),
            key_direction="positive",
        )
        for index in range(8)
    )
    return SimpleNamespace(items=items, source_categories=(1, 2, 3, 4, 5))


def test_full_bank_reference_is_symmetric_for_symmetric_parameters_and_middle_answers():
    profile = _symmetric_eight_item_profile()

    theta, standard_error = _independent_full_bank_eap(profile, (3,) * 8)

    assert abs(theta) < 1e-12
    assert 0.0 < standard_error < 1.0


def test_full_bank_reference_reflects_all_low_vs_all_high_categories():
    profile = _symmetric_eight_item_profile()

    low_theta, _ = _independent_full_bank_eap(profile, (1,) * 8)
    high_theta, _ = _independent_full_bank_eap(profile, (5,) * 8)

    assert low_theta < 0.0 < high_theta
    assert high_theta == pytest.approx(-low_theta, abs=1e-12)


def test_full_bank_reference_rejects_out_of_scale_observations():
    profile = _symmetric_eight_item_profile()

    with pytest.raises(FullBankComparisonError) as error:
        _independent_full_bank_eap(profile, (1, 2, 3, 4, 5, 1, 2, 9))

    assert error.value.code == "RESPONSE_CATEGORY_INVALID"
