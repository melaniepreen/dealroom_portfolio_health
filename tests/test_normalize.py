from sentinel.model import FEATURE_NAMES
from sentinel.normalize import (
    employee_points_from_headcount,
    funding_rounds,
    timeseries_points,
)


def test_hiring_is_not_a_training_column():
    assert "university" in FEATURE_NAMES
    assert "prior_startup" in FEATURE_NAMES
    assert "industry_position" in FEATURE_NAMES
    assert "hiring" not in FEATURE_NAMES


def test_debt_round_stays_off_the_venture_clock():
    rounds = funding_rounds(
        [
            {"year": 2025, "month": 3, "amount": {"value": 2500000}, "standardized_round": "SEED", "is_vc_round": True},
            {"year": 2025, "month": 11, "amount": 500000, "standardized_round": "Debt", "is_vc_round": False},
        ]
    )
    assert rounds[0]["standardized_round"] == "Seed"
    assert rounds[0]["amount"] == 2500000
    assert rounds[1]["is_vc_round"] is False


def test_headcount_shares_are_not_employee_counts():
    assert employee_points_from_headcount([{"department": "engineering", "percentage": 40}]) == []


def test_2026_industry_points_are_partial():
    points = timeseries_points([{"year": 2026, "month": 2, "value": 10}, {"year": 2025, "month": 12, "value": 9}])
    assert points[0]["partial"] is True
    assert points[1]["partial"] is False
