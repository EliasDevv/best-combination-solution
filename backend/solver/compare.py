"""Single-pass entry point: one stage-1 reduction shared by solve and Pareto front."""

from dataclasses import dataclass, replace

from .index import BitIndex
from .pareto import pareto_front_reduced
from .reprice import covered_games_mask, drop_redundant
from .setcover import relevant_coverages, solve_reduced
from .types import PackageCoverage, ParetoPoint, Query, Solution


@dataclass(frozen=True, slots=True)
class CompareResult:
    """Everything one compare request needs, from a single reduction pass."""

    target_mask: int
    coverages: tuple[PackageCoverage, ...]
    solution: Solution
    pareto: tuple[ParetoPoint, ...]


def compare(index: BitIndex, query: Query, max_points: int = 10) -> CompareResult:
    """Solve one query end to end — the only entry point the API needs.

    Runs stage 1 exactly once and shares it with both consumers, which is the
    whole reason this facade exists: solving and building the Pareto front
    separately would reduce and re-price the same packages twice.

    The pipeline is: reduce, solve exactly, trim the winner of packages that
    earn nothing once re-priced, then build the front. Two subtleties:

    - The solve optimizes *static* costs, so a combination it rejected can
      re-price cheaper than the one it picked. The front's candidate pools
      are re-priced too, so if one of them beats the winner at the same or
      better coverage it is adopted — that keeps the reported best
      combination equal to the top Pareto point instead of contradicting it.
    - ``exact`` is carried over from the search and never upgraded here.
      Re-pricing lowers a price; it does not turn a time-capped result into
      a proven optimum.
    """
    game_count = len(index.game_ids)
    target, coverages = relevant_coverages(index, query)
    solution = solve_reduced(game_count, query, target, coverages)
    by_id = {cov.package.id: cov for cov in coverages}
    chosen = [by_id[pid] for pid in solution.package_ids]
    if chosen:
        # strip redundant packages (coverage- and cost-neutral), then re-price
        kept, repriced = drop_redundant(
            game_count,
            query.requirement,
            query.billing,
            chosen,
            index.month_mask,
        )
        solution = replace(
            solution,
            package_ids=tuple(sorted(cov.package.id for cov in kept)),
            cost_cents=repriced,
        )
    # the front prices in min_price weights; only then is the solve optimum reusable
    known = solution if query.objective == "min_price" and solution.package_ids else None
    pareto = pareto_front_reduced(
        game_count,
        query,
        target,
        coverages,
        max_points,
        known_optimal=known,
        month_mask=index.month_mask,
    )
    if query.objective == "min_price" and pareto:
        top = pareto[0]
        # a pool may re-price cheaper than the static optimum; adopt it so the
        # top Pareto point stays equal to the solution
        if top.coverage > solution.coverage or (
            top.coverage == solution.coverage and top.cost_cents < solution.cost_cents
        ):
            top_chosen = [by_id[pid] for pid in top.package_ids]
            solution = Solution(
                package_ids=tuple(top.package_ids),
                cost_cents=top.cost_cents,
                covered_mask=covered_games_mask(query.requirement, top_chosen),
                coverage=top.coverage,
                exact=solution.exact,
            )
    return CompareResult(
        target_mask=target,
        coverages=tuple(coverages),
        solution=solution,
        pareto=tuple(pareto),
    )
