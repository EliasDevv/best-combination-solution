"""Tests for solver.pricing — the package cost model."""

import pytest

from solver.pricing import months_needed, package_cost_cents
from solver.types import PackageInfo


def make_package(**overrides) -> PackageInfo:
    defaults = {
        "id": 1,
        "name": "Test Package",
        "monthly_price_cents": 999,
        "yearly_monthly_price_cents": 899,
    }
    return PackageInfo(**{**defaults, **overrides})


class TestMonthsNeeded:
    def test_empty_selection_needs_no_months(self) -> None:
        assert months_needed(frozenset()) == 0

    def test_counts_distinct_months(self) -> None:
        assert months_needed(frozenset({"2024-08"})) == 1
        assert months_needed(frozenset({"2024-08", "2024-09", "2025-02"})) == 3


class TestPackageCostCents:
    def test_monthly_chained_pays_only_needed_months(self) -> None:
        package = make_package(monthly_price_cents=1000, yearly_monthly_price_cents=None)
        assert package_cost_cents(package, months=3, billing="monthly_chained") == 3000

    def test_monthly_chained_is_capped_by_yearly_price(self) -> None:
        package = make_package(monthly_price_cents=1000, yearly_monthly_price_cents=500)
        # 10 months at 1000 = 10000, but 12 x 500 = 6000 is cheaper.
        assert package_cost_cents(package, months=10, billing="monthly_chained") == 6000

    def test_yearly_only_package_falls_back_to_yearly_under_chained(self) -> None:
        package = make_package(monthly_price_cents=None, yearly_monthly_price_cents=2499)
        assert package_cost_cents(package, months=1, billing="monthly_chained") == 12 * 2499

    def test_monthly_only_package_is_unbookable_yearly(self) -> None:
        package = make_package(monthly_price_cents=999, yearly_monthly_price_cents=None)
        assert package_cost_cents(package, months=5, billing="yearly") is None

    def test_yearly_ignores_month_count(self) -> None:
        package = make_package(yearly_monthly_price_cents=800)
        assert package_cost_cents(package, months=1, billing="yearly") == 9600
        assert package_cost_cents(package, months=12, billing="yearly") == 9600

    def test_unbookable_package_costs_none(self) -> None:
        package = make_package(monthly_price_cents=None, yearly_monthly_price_cents=None)
        assert package_cost_cents(package, months=1, billing="flexible") is None
        assert package_cost_cents(package, months=1, billing="yearly") is None
        assert package_cost_cents(package, months=1, billing="monthly_chained") is None

    def test_price_zero_is_bookable_not_none(self) -> None:
        package = make_package(monthly_price_cents=0, yearly_monthly_price_cents=None)
        assert package_cost_cents(package, months=4, billing="monthly_chained") == 0

    @pytest.mark.parametrize("months", [0, 1, 7, 12, 24])
    def test_flexible_equals_monthly_chained(self, months: int) -> None:
        # The yearly cap makes monthly_chained already "cheaper of the two".
        for package in (
            make_package(),
            make_package(monthly_price_cents=None),
            make_package(yearly_monthly_price_cents=None),
        ):
            assert package_cost_cents(package, months, "flexible") == package_cost_cents(
                package, months, "monthly_chained"
            )

    def test_zero_months_costs_zero_when_monthly_bookable(self) -> None:
        package = make_package(monthly_price_cents=1200, yearly_monthly_price_cents=None)
        assert package_cost_cents(package, months=0, billing="monthly_chained") == 0
