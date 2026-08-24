"""Tests for the solver data structures (solver.types).

Algorithm tests live in the per-module files: test_pricing, test_index,
test_setcover, test_pareto.
"""

import dataclasses

import pytest

from solver.types import PackageInfo, ParetoPoint, Query, Solution


def make_package(**overrides) -> PackageInfo:
    defaults = {
        "id": 1,
        "name": "Test Package",
        "monthly_price_cents": 999,
        "yearly_monthly_price_cents": 899,
    }
    return PackageInfo(**{**defaults, **overrides})


class TestTypes:
    def test_package_info_is_frozen(self) -> None:
        package = make_package()
        with pytest.raises(dataclasses.FrozenInstanceError):
            package.name = "other"  # type: ignore[misc]

    def test_package_info_allows_null_prices(self) -> None:
        package = make_package(monthly_price_cents=None, yearly_monthly_price_cents=None)
        assert package.monthly_price_cents is None
        assert package.yearly_monthly_price_cents is None

    def test_query_construction(self) -> None:
        query = Query(
            team_masks=(0b1010, 0b0110),
            date_from=None,
            date_to=None,
            requirement="live",
            objective="min_price",
            billing="monthly_chained",
        )
        assert query.team_masks == (0b1010, 0b0110)

    def test_solution_and_pareto_point(self) -> None:
        solution = Solution(package_ids=(7, 12), cost_cents=6998, covered_mask=0b111, coverage=1.0)
        point = ParetoPoint(coverage=1.0, cost_cents=6998, package_ids=(7, 12))
        assert solution.cost_cents == point.cost_cents
