"""Re-price a chosen combination: each package pays only the months it is needed in."""

from collections.abc import Mapping, Sequence

from .pricing import package_cost_cents
from .types import Billing, PackageCoverage, Requirement

_EXACT_MONTH_LIMIT = 12  # brute-force month sub-cover up to this many candidates, greedy beyond


def covered_games_mask(requirement: Requirement, chosen: Sequence[PackageCoverage]) -> int:
    """Which games a set of packages actually covers, as one game-bit mask.

    Plain union for ``live`` and ``highlights``. For ``both`` it is the
    *intersection* of the two unions: a game counts only when the combination
    supplies both halves, though not necessarily from the same package.
    """
    live = 0
    highlights = 0
    for cov in chosen:
        live |= cov.live_mask
        highlights |= cov.highlight_mask
    if requirement == "live":
        return live
    if requirement == "highlights":
        return highlights
    return live & highlights


def _cost_at(cov: PackageCoverage, months: int, billing: Billing) -> int:
    if months == 0:
        return 0
    cost = package_cost_cents(cov.package, months, billing)
    assert cost is not None  # chosen packages are bookable
    return cost


def _min_month_cover(
    rem: int,
    candidates: list[int],
    serve: list[int],
    weights: dict[int, int],
    package_ids: list[int],
) -> list[int]:
    if len(candidates) <= _EXACT_MONTH_LIMIT:
        best_key: tuple[int, int, tuple[int, ...]] | None = None
        best: list[int] = list(candidates)
        for subset in range(1, 1 << len(candidates)):
            picked = [candidates[i] for i in range(len(candidates)) if subset >> i & 1]
            cover = 0
            for idx in picked:
                cover |= serve[idx]
            if rem & ~cover:
                continue
            key = (
                sum(weights[idx] for idx in picked),
                len(picked),
                tuple(package_ids[idx] for idx in picked),
            )
            if best_key is None or key < best_key:
                best_key, best = key, picked
        return best

    uncovered = rem
    available = list(candidates)
    picked_greedy: list[int] = []
    while uncovered:
        best_idx: int | None = None
        best_new = 0
        for idx in available:
            new = (serve[idx] & uncovered).bit_count()
            if new == 0:
                continue
            if best_idx is None:
                best_idx, best_new = idx, new
                continue
            # weights[idx]/new < best ratio, without floats
            lhs = weights[idx] * best_new
            rhs = weights[best_idx] * new
            if lhs < rhs or (
                lhs == rhs
                and (weights[idx], package_ids[idx]) < (weights[best_idx], package_ids[best_idx])
            ):
                best_idx, best_new = idx, new
        if best_idx is None:
            break  # unreachable: every rem bit is servable
        picked_greedy.append(best_idx)
        available.remove(best_idx)
        uncovered &= ~serve[best_idx]
    return picked_greedy


def drop_redundant(
    game_count: int,
    requirement: Requirement,
    billing: Billing,
    chosen: Sequence[PackageCoverage],
    month_mask: Mapping[str, int],
) -> tuple[list[PackageCoverage], int]:
    """Drop packages that neither add coverage nor lower the re-priced cost.

    Greedy may pick a zero-cost candidate first (unbeatable weight ratio)
    that later picks fully overshadow, and branch & bound keeps the extra
    because the slimmer alternative is not strictly cheaper. Coverage alone
    is not enough to call a package redundant: a covered-elsewhere package
    can still take over months and make the combination re-price cheaper,
    so removal also requires an unchanged re-priced cost. Checked most-
    expensive-first (static cost, ties by package id) so mutually
    replaceable packages resolve to the cheapest subset; repeats until
    nothing is removable. Returns the kept packages and their re-priced cost.
    """
    kept = list(chosen)
    covered = covered_games_mask(requirement, kept)
    cost = reprice_combination(game_count, requirement, billing, covered, kept, month_mask)
    while True:
        for cov in sorted(kept, key=lambda c: (-(c.cost_cents or 0), c.package.id)):
            rest = [c for c in kept if c is not cov]
            if covered_games_mask(requirement, rest) != covered:
                continue
            rest_cost = reprice_combination(
                game_count, requirement, billing, covered, rest, month_mask
            )
            if rest_cost <= cost:
                kept, cost = rest, rest_cost
                break
        else:
            return kept, cost


def reprice_combination(
    game_count: int,
    requirement: Requirement,
    billing: Billing,
    covered_games: int,
    chosen: Sequence[PackageCoverage],
    month_mask: Mapping[str, int],
) -> int:
    """What a combination really costs once each package pays only its months.

    The search prices every package over the months of everything it *could*
    serve, because a cost that depends on the other packages chosen would not
    be additive and would break branch & bound. Once the set is fixed that
    constraint is gone, so the needs are re-assigned:

    1. **Forced pass** — a need only one chosen package can serve pins that
       package into that month; there is no choice to make.
    2. **Per-month sub-cover** — whatever is still uncovered in a month is
       covered by the cheapest subset of the remaining packages, brute-forced
       up to 12 candidates and greedy beyond. Weights are *marginal*: what one
       more month adds for that package, which is zero once it has hit its
       yearly cap, so a package already paid for keeps absorbing months free.

    Returns the summed cost; never above the static one the search used.
    """
    if covered_games == 0 or not chosen:
        return 0
    ordered = sorted(chosen, key=lambda cov: cov.package.id)
    package_ids = [cov.package.id for cov in ordered]

    # need space: game bits, doubled for "both" (low half live, high half highlights)
    if requirement == "both":
        serve = [
            (cov.live_mask & covered_games) | ((cov.highlight_mask & covered_games) << game_count)
            for cov in ordered
        ]
        needs = covered_games | (covered_games << game_count)
        month_needs = {m: (mask | (mask << game_count)) & needs for m, mask in month_mask.items()}
    elif requirement == "live":
        serve = [cov.live_mask & covered_games for cov in ordered]
        needs = covered_games
        month_needs = {m: mask & needs for m, mask in month_mask.items()}
    else:
        serve = [cov.highlight_mask & covered_games for cov in ordered]
        needs = covered_games
        month_needs = {m: mask & needs for m, mask in month_mask.items()}
    months = sorted(m for m, need in month_needs.items() if need)

    counts = [0] * len(ordered)
    active: dict[str, set[int]] = {m: set() for m in months}

    def activate(idx: int, month: str) -> None:
        if idx not in active[month]:
            active[month].add(idx)
            counts[idx] += 1

    # forced pass: needs only one chosen package can serve
    once = 0
    multi = 0
    for mask in serve:
        multi |= once & mask
        once |= mask
    for m in months:
        unique = month_needs[m] & ~multi
        if unique == 0:
            continue
        for idx, mask in enumerate(serve):
            if mask & unique:
                activate(idx, m)

    # rest: cheapest sub-cover per month; marginal weights make a package past
    # its yearly cap add further months for free
    for m in months:
        covered = 0
        for idx in active[m]:
            covered |= serve[idx]
        rem = month_needs[m] & ~covered
        if rem == 0:
            continue
        candidates = [
            idx for idx in range(len(ordered)) if idx not in active[m] and serve[idx] & rem
        ]
        weights = {
            idx: _cost_at(ordered[idx], counts[idx] + 1, billing)
            - _cost_at(ordered[idx], counts[idx], billing)
            for idx in candidates
        }
        for idx in _min_month_cover(rem, candidates, serve, weights, package_ids):
            activate(idx, m)

    return sum(_cost_at(cov, counts[idx], billing) for idx, cov in enumerate(ordered))
