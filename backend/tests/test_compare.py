"""Tests for solver.compare — the single-pass facade over the pipeline.

The facade must be a pure refactor: identical results to calling
``relevant_coverages`` + ``solve`` + ``pareto_front`` separately, while
running the reduction once and (for ``min_price``) branch & bound once.
"""

import random

import pytest

from solver.compare import compare
from solver.pareto import pareto_front
from solver.setcover import relevant_coverages, solve
from solver.types import Objective, Requirement

from .test_setcover import make_index, make_query


def _random_instance(seed: int):
    """Same shape as the brute-force cross-check instances in test_setcover."""
    rng = random.Random(seed)
    n_games = rng.randint(3, 10)
    n_packages = rng.randint(2, 8)
    months = [rng.choice(["2024-08", "2024-09", "2024-10"]) for _ in range(n_games)]
    packages: dict[int, tuple[int | None, int | None]] = {}
    live: dict[int, list[int]] = {}
    highlights: dict[int, list[int]] = {}
    for pid in range(1, n_packages + 1):
        monthly = rng.choice([None, rng.randint(1, 50) * 100])
        yearly = rng.choice([None, rng.randint(1, 40) * 100])
        packages[pid] = (monthly, yearly)
        live[pid] = [bit for bit in range(n_games) if rng.random() < 0.4]
        highlights[pid] = [bit for bit in range(n_games) if rng.random() < 0.4]
    return make_index(months, packages, live, highlights)


class TestCompareFacade:
    @pytest.mark.parametrize("seed", range(20))
    @pytest.mark.parametrize("objective", ["min_price", "min_packages"])
    @pytest.mark.parametrize("requirement", ["live", "both"])
    def test_matches_separate_calls(
        self, seed: int, objective: Objective, requirement: Requirement
    ) -> None:
        index = _random_instance(seed)
        query = make_query(objective=objective, requirement=requirement)

        result = compare(index, query)

        target, coverages = relevant_coverages(index, query)
        assert result.target_mask == target
        assert result.coverages == tuple(coverages)
        front = pareto_front(index, query)
        assert list(result.pareto) == front

        # The facade re-prices the solve result (and may adopt a Pareto pool
        # that re-prices cheaper for min_price), so compare against solve()
        # via invariants rather than equality.
        static = solve(index, query)
        solution = result.solution
        assert solution.cost_cents <= static.cost_cents
        assert solution.coverage >= static.coverage
        assert solution.exact == static.exact
        if objective == "min_price" and front:
            assert solution.package_ids in {static.package_ids, front[0].package_ids}
            assert solution.cost_cents == front[0].cost_cents
            assert solution.coverage == front[0].coverage
        else:
            assert solution.package_ids == static.package_ids

    def test_pareto_front_stays_dominance_ordered_after_repricing(self) -> None:
        for seed in range(20):
            result = compare(_random_instance(seed), make_query())
            front = list(result.pareto)
            assert all(a.coverage > b.coverage for a, b in zip(front, front[1:], strict=False))
            assert all(a.cost_cents > b.cost_cents for a, b in zip(front, front[1:], strict=False))

    def test_adopts_pool_that_reprices_cheaper(self) -> None:
        """A covers Aug+Sep (static 1000), B covers Sep (100). Statically A
        alone (1000) beats A+B (1100), but re-priced A+B costs 500+100=600 —
        the facade must adopt it and keep pareto[0] == best_combination."""
        index = make_index(
            ["2024-08", "2024-09"], {1: (500, None), 2: (100, None)}, {1: [0, 1], 2: [1]}
        )
        query = make_query()
        assert solve(index, query).package_ids == (1,)

        result = compare(index, query)
        assert result.solution.package_ids == (1, 2)
        assert result.solution.cost_cents == 600
        assert result.solution.coverage == 1.0
        assert result.pareto[0].package_ids == (1, 2)
        assert result.pareto[0].cost_cents == 600

    def test_zero_cost_redundant_package_is_dropped(self) -> None:
        """Greedy grabs the free P2 first (weight-per-bit ratio 0) for game
        0's highlights; P1 then covers everything on its own. Branch & bound
        keeps the free extra (dropping it is not strictly cheaper), so the
        redundancy pass must slim the result to P1 — the ZDF Free-TV case."""
        index = make_index(
            ["2024-08", "2024-08"],
            {1: (1000, None), 2: (0, None)},
            live={1: [0, 1]},
            highlights={1: [0, 1], 2: [0]},
        )
        query = make_query(requirement="both")
        assert solve(index, query).package_ids == (1, 2)  # pre-pass artifact

        result = compare(index, query)
        assert result.solution.package_ids == (1,)
        assert result.solution.cost_cents == 1000
        assert result.solution.coverage == 1.0
        assert result.pareto[0].package_ids == (1,)

    def test_empty_target(self) -> None:
        index = make_index(["2024-08"], {1: (100, None)}, {1: [0]})
        result = compare(index, make_query(team_masks=(0,)))
        assert result.target_mask == 0
        assert result.solution.coverage == 1.0
        assert result.solution.package_ids == ()
        assert result.pareto == ()

    def test_min_price_skips_second_branch_and_bound(self, monkeypatch) -> None:
        """For min_price the front must reuse the solve optimum, not re-search."""

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("pareto_front re-ran branch & bound")

        index = _random_instance(3)
        monkeypatch.setattr("solver.pareto.branch_and_bound", boom)
        result = compare(index, make_query(objective="min_price"))
        if result.pareto:
            assert result.pareto[0].package_ids == result.solution.package_ids
            assert result.pareto[0].cost_cents == result.solution.cost_cents

    def test_min_packages_front_still_prices_min_price(self) -> None:
        """min_packages weights are not reusable — the front runs its own search
        and must equal the standalone min_price-weighted front."""
        index = _random_instance(5)
        query = make_query(objective="min_packages")
        assert list(compare(index, query).pareto) == pareto_front(index, query)
