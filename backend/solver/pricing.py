"""What a package costs for a given number of months under a billing mode."""

from .types import Billing, PackageInfo


def months_needed(month_keys: frozenset[str]) -> int:
    """How many months must be paid for a set of ``YYYY-MM`` keys.

    Chained months are billed per distinct calendar month, not per game and
    not per elapsed month: two games in the same August cost one month, and a
    gap month nobody needs is never paid for.
    """
    return len(month_keys)


def package_cost_cents(
    package: PackageInfo,
    months: int,
    billing: Billing,
) -> int | None:
    """None = not bookable under this billing, never 0."""
    yearly_total = (
        None
        if package.yearly_monthly_price_cents is None
        else 12 * package.yearly_monthly_price_cents
    )
    if billing == "yearly":
        return yearly_total

    # chained months are capped at the yearly price, so flexible == monthly_chained
    candidates = []
    if package.monthly_price_cents is not None:
        candidates.append(months * package.monthly_price_cents)
    if yearly_total is not None:
        candidates.append(yearly_total)
    return min(candidates) if candidates else None
