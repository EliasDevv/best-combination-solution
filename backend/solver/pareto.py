"""Coverage/price trade-off front for queries where full coverage is impossible."""

from collections.abc import Mapping

from .index import BitIndex
from .reprice import drop_redundant
from .setcover import (
    Candidate,
    _fold_covered_games,
    _greedy_prefixes,
    _solution_from,
    branch_and_bound,
    build_candidates,
    prune_dominated,
    relevant_coverages,
)
from .types import PackageCoverage, ParetoPoint, Query, Solution


def _marginal_coverage_prefixes(
    chosen: list[Candidate], search_target: int
) -> list[list[Candidate]]:
    uncovered = search_target
    remaining = list(chosen)
    ordered: list[Candidate] = []
    prefixes: list[list[Candidate]] = []
    while remaining:
        best = max(
            remaining,
            key=lambda c: ((c.mask & uncovered).bit_count(), -c.cost_cents, -c.coverage.package.id),
        )
        remaining.remove(best)
        ordered.append(best)
        uncovered &= ~best.mask
        prefixes.append(list(ordered))
    return prefixes


def pareto_front_reduced(
    game_count: int,
    query: Query,
    target: int,
    coverages: list[PackageCoverage],
    max_points: int = 10,
    known_optimal: Solution | None = None,
    *,
    month_mask: Mapping[str, int],
) -> list[ParetoPoint]:
    """The coverage/price front for an already-reduced query.

    Answers "what if I accept less than everything": for each achievable
    coverage level, the cheapest combination reaching it, as a monotone curve
    sorted by descending coverage where every later point is strictly cheaper.

    Candidates are not searched per coverage level (that would be one exact
    solve per level). They are pooled from four sources — the exact optimum,
    every greedy prefix, every single package, and the optimum re-ordered by
    marginal coverage — then re-priced, deduplicated and dominance-filtered.
    That makes the front a *lower envelope of good candidates*, exact at the
    top point and honest but not provably minimal in between.

    Always priced in ``min_price`` weights, whatever the query's objective, so
    ``known_optimal`` may only be passed in when it came from a min_price
    search. ``month_mask`` is keyword-only because passing it positionally
    behind ``known_optimal`` reads like a fifth tuning knob rather than data.
    """
    if target == 0 or max_points <= 0:
        return []
    search_target, candidates = build_candidates(
        target, coverages, query.requirement, "min_price", game_count
    )
    if not candidates or search_target == 0:
        return []
    pruned = prune_dominated(candidates)

    greedy_prefixes = _greedy_prefixes(search_target, pruned)
    # known_optimal is only valid if it came from a min_price search (caller guarantees)
    if known_optimal is None:
        upper = _solution_from(greedy_prefixes[-1] if greedy_prefixes else [], search_target)
        optimal = branch_and_bound(search_target, pruned, upper)
    else:
        optimal = known_optimal
    by_id = {cand.coverage.package.id: cand for cand in pruned}
    optimal_candidates = [by_id[pid] for pid in optimal.package_ids if pid in by_id]
    # trim the optimum before deriving pools so optimal_ids matches its
    # trimmed pool in the tie-break below
    kept, _ = drop_redundant(
        game_count,
        query.requirement,
        query.billing,
        [cand.coverage for cand in optimal_candidates],
        month_mask,
    )
    kept_ids = {cov.package.id for cov in kept}
    optimal_candidates = [
        cand for cand in optimal_candidates if cand.coverage.package.id in kept_ids
    ]

    # pools: exact optimum, greedy prefixes, singletons, optimum by marginal coverage
    pools: list[list[Candidate]] = [optimal_candidates]
    pools.extend(greedy_prefixes)
    pools.extend([cand] for cand in pruned)
    pools.extend(_marginal_coverage_prefixes(optimal_candidates, search_target))

    optimal_ids = tuple(sorted(cand.coverage.package.id for cand in optimal_candidates))
    seen: set[tuple[int, ...]] = set()
    scored: list[tuple[float, int, tuple[int, ...]]] = []
    for pool in pools:
        if not pool:
            continue
        raw_ids = tuple(sorted(cand.coverage.package.id for cand in pool))
        if raw_ids in seen:
            continue
        seen.add(raw_ids)
        covered = 0
        for cand in pool:
            covered |= cand.mask
        games = _fold_covered_games(covered & search_target, query.requirement, game_count)
        coverage = games.bit_count() / target.bit_count()
        kept_pool, cost = drop_redundant(
            game_count,
            query.requirement,
            query.billing,
            [cand.coverage for cand in pool],
            month_mask,
        )
        ids = tuple(sorted(cov.package.id for cov in kept_pool))
        if ids != raw_ids:
            if ids in seen:
                continue
            seen.add(ids)
        scored.append((coverage, cost, ids))

    # ascending price, keep strict coverage gains; optimum wins exact ties
    front: list[tuple[float, int, tuple[int, ...]]] = []
    best_coverage = 0.0
    for coverage, cost, ids in sorted(
        scored, key=lambda p: (p[1], -p[0], p[2] != optimal_ids, p[2])
    ):
        if coverage > best_coverage:
            front.append((coverage, cost, ids))
            best_coverage = coverage

    front.sort(key=lambda p: -p[0])
    return [
        ParetoPoint(coverage=coverage, cost_cents=cost, package_ids=ids)
        for coverage, cost, ids in front[:max_points]
    ]


def pareto_front(index: BitIndex, query: Query, max_points: int = 10) -> list[ParetoPoint]:
    """Points sorted by descending coverage, each strictly cheaper than the previous."""
    target, coverages = relevant_coverages(index, query)
    return pareto_front_reduced(
        len(index.game_ids), query, target, coverages, max_points, month_mask=index.month_mask
    )
