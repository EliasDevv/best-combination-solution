"""Tests for solver.pareto — the coverage/price trade-off front."""

from solver.pareto import pareto_front
from solver.setcover import solve
from tests.test_setcover import make_index, make_query


class TestParetoFront:
    def test_top_point_equals_exact_solution_at_full_coverage(self) -> None:
        index = make_index(
            ["2024-08"] * 3,
            {1: (100, None), 2: (200, None)},
            {1: [0, 1], 2: [2]},
        )
        query = make_query()
        front = pareto_front(index, query)
        solution = solve(index, query)
        assert front[0].coverage == 1.0
        assert front[0].cost_cents == solution.cost_cents == 300
        assert front[0].package_ids == solution.package_ids

    def test_uncoverable_game_caps_top_coverage(self) -> None:
        index = make_index(["2024-08"] * 2, {1: (100, None)}, {1: [0]})
        front = pareto_front(index, make_query())
        assert front[0].coverage == 0.5

    def test_front_is_monotone(self) -> None:
        # Distinct coverage levels at distinct prices.
        index = make_index(
            ["2024-08"] * 4,
            {1: (1000, None), 2: (300, None), 3: (150, None)},
            {1: [0, 1, 2, 3], 2: [0, 1], 3: [0]},
        )
        front = pareto_front(index, make_query())
        assert len(front) >= 2
        coverages = [p.coverage for p in front]
        costs = [p.cost_cents for p in front]
        assert coverages == sorted(coverages, reverse=True)
        assert costs == sorted(costs, reverse=True)
        assert len(set(coverages)) == len(coverages)

    def test_max_points_truncates_from_the_cheap_end(self) -> None:
        index = make_index(
            ["2024-08"] * 4,
            {1: (1000, None), 2: (300, None), 3: (150, None)},
            {1: [0, 1, 2, 3], 2: [0, 1], 3: [0]},
        )
        full = pareto_front(index, make_query())
        top_only = pareto_front(index, make_query(), max_points=1)
        assert top_only == full[:1]

    def test_empty_target_returns_empty_front(self) -> None:
        index = make_index(["2024-08"], {1: (100, None)}, {1: [0]})
        assert pareto_front(index, make_query(team_masks=(0,))) == []

    def test_nothing_bookable_returns_empty_front(self) -> None:
        index = make_index(["2024-08"], {1: (None, None)}, {1: [0]})
        assert pareto_front(index, make_query()) == []

    def test_points_contain_no_redundant_packages(self) -> None:
        # Free P2 only mirrors highlights P1 already has; no pool (greedy
        # prefixes included) may surface it in the front.
        index = make_index(
            ["2024-08", "2024-08"],
            {1: (1000, None), 2: (0, None)},
            live={1: [0, 1]},
            highlights={1: [0, 1], 2: [0]},
        )
        front = pareto_front(index, make_query(requirement="both"))
        assert front
        for point in front:
            assert 2 not in point.package_ids
