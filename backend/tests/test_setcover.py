"""Tests for solver.setcover — the weighted set-cover pipeline.

The heart of this file is the brute-force cross-check: on small random
instances the branch & bound result must match exhaustive enumeration for
both objectives.
"""

import itertools
import random
from datetime import UTC, date, datetime

import pytest

from solver.index import BitIndex, build_index
from solver.setcover import (
    Candidate,
    build_candidates,
    greedy_cover,
    prune_dominated,
    relevant_coverages,
    solve,
)
from solver.types import Billing, Objective, PackageCoverage, PackageInfo, Query


def make_query(**overrides) -> Query:
    defaults = {
        "team_masks": (),
        "date_from": None,
        "date_to": None,
        "requirement": "live",
        "objective": "min_price",
        "billing": "monthly_chained",
    }
    return Query(**{**defaults, **overrides})


def make_index(
    game_months: list[str],
    packages: dict[int, tuple[int | None, int | None]],
    live: dict[int, list[int]],
    highlights: dict[int, list[int]] | None = None,
) -> BitIndex:
    """Small-index builder: one game per entry of ``game_months`` (bit = list
    position), packages as id -> (monthly, yearly_monthly), offers as
    id -> list of game bits.
    """
    highlights = highlights or {}
    games = [
        {
            "id": bit + 1,
            "team_home": f"home {bit}",
            "team_away": f"away {bit}",
            "starts_at": datetime(int(month[:4]), int(month[5:7]), 1 + bit, tzinfo=UTC),
            "tournament_name": "League",
        }
        for bit, month in enumerate(game_months)
    ]
    package_rows = [
        {"id": pid, "name": f"P{pid}", "monthly_price_cents": m, "yearly_monthly_price_cents": y}
        for pid, (m, y) in packages.items()
    ]
    offer_map: dict[tuple[int, int], dict] = {}
    for pid, bits in live.items():
        for bit in bits:
            offer_map[(bit + 1, pid)] = {
                "game_id": bit + 1,
                "package_id": pid,
                "live": True,
                "highlights": False,
            }
    for pid, bits in highlights.items():
        for bit in bits:
            key = (bit + 1, pid)
            if key in offer_map:
                offer_map[key]["highlights"] = True
            else:
                offer_map[key] = {
                    "game_id": bit + 1,
                    "package_id": pid,
                    "live": False,
                    "highlights": True,
                }
    return build_index(games=games, packages=package_rows, offers=list(offer_map.values()))


class TestRelevantCoverages:
    def test_date_range_edge_trimming(self) -> None:
        index = make_index(["2024-08", "2024-08", "2024-09"], {1: (100, None)}, {1: [0, 1, 2]})
        # Games start on Aug 1, Aug 2, Sep 3. From Aug 2 on: bits 1 and 2.
        query = make_query(date_from=date(2024, 8, 2), date_to=None)
        target, coverages = relevant_coverages(index, query)
        assert target == 0b110
        # Inclusive upper edge: up to Aug 2 keeps bits 0 and 1.
        query = make_query(date_from=None, date_to=date(2024, 8, 2))
        target, _ = relevant_coverages(index, query)
        assert target == 0b011

    def test_requirement_selects_mask(self) -> None:
        index = make_index(
            ["2024-08", "2024-08"], {1: (100, None)}, live={1: [0]}, highlights={1: [1]}
        )
        _, live_cov = relevant_coverages(index, make_query(requirement="live"))
        _, hl_cov = relevant_coverages(index, make_query(requirement="highlights"))
        assert live_cov[0].live_mask == 0b01
        assert hl_cov[0].highlight_mask == 0b10

    def test_unbookable_package_excluded(self) -> None:
        index = make_index(["2024-08"], {1: (None, None), 2: (100, None)}, {1: [0], 2: [0]})
        _, coverages = relevant_coverages(index, make_query())
        assert [c.package.id for c in coverages] == [2]

    def test_monthly_only_package_excluded_under_yearly_billing(self) -> None:
        index = make_index(["2024-08"], {1: (100, None)}, {1: [0]})
        _, coverages = relevant_coverages(index, make_query(billing="yearly"))
        assert coverages == []

    def test_cost_uses_months_of_own_clipped_coverage(self) -> None:
        # Package spans Aug+Sep games, but the team filter clips it to Aug.
        index = make_index(["2024-08", "2024-09"], {1: (1000, None)}, {1: [0, 1]})
        target, coverages = relevant_coverages(index, make_query())
        assert coverages[0].cost_cents == 2000  # both months
        query = make_query(team_masks=(0b01,))
        _, clipped = relevant_coverages(index, query)
        assert clipped[0].cost_cents == 1000  # only August remains

    def test_empty_team_masks_means_all_games(self) -> None:
        index = make_index(["2024-08", "2024-08"], {1: (100, None)}, {1: [0]})
        target, _ = relevant_coverages(index, make_query(team_masks=()))
        assert target == 0b11


def make_candidate(package_id: int, mask: int, weight: int) -> Candidate:
    info = PackageInfo(
        id=package_id,
        name=f"P{package_id}",
        monthly_price_cents=weight,
        yearly_monthly_price_cents=None,
    )
    coverage = PackageCoverage(package=info, live_mask=mask, highlight_mask=0, cost_cents=weight)
    return Candidate(mask=mask, weight=weight, cost_cents=weight, coverage=coverage)


class TestPruneDominated:
    def test_cheaper_superset_dominates(self) -> None:
        a = make_candidate(1, 0b011, 200)
        b = make_candidate(2, 0b111, 100)
        assert prune_dominated([a, b]) == [b]

    def test_equal_twins_keep_lower_id(self) -> None:
        a = make_candidate(5, 0b11, 100)
        b = make_candidate(3, 0b11, 100)
        kept = prune_dominated([a, b])
        assert [c.coverage.package.id for c in kept] == [3]

    def test_incomparable_pair_both_survive(self) -> None:
        a = make_candidate(1, 0b01, 100)
        b = make_candidate(2, 0b10, 50)
        assert len(prune_dominated([a, b])) == 2


class TestSolve:
    def test_single_package_full_cover(self) -> None:
        index = make_index(["2024-08", "2024-08"], {1: (500, None)}, {1: [0, 1]})
        solution = solve(index, make_query())
        assert solution.package_ids == (1,)
        assert solution.cost_cents == 500
        assert solution.coverage == 1.0
        assert solution.covered_mask == 0b11

    def test_greedy_trap_branch_and_bound_wins(self) -> None:
        # Greedy picks A (best ratio 45/game), then must add B: 90+100=190.
        # Optimal is C alone at 150.
        index = make_index(
            ["2024-08"] * 3,
            {1: (90, None), 2: (100, None), 3: (150, None)},
            {1: [0, 1], 2: [2], 3: [0, 1, 2]},
        )
        query = make_query()
        target, coverages = relevant_coverages(index, query)
        _, candidates = build_candidates(target, coverages, "live", "min_price", 3)
        greedy = greedy_cover(target, candidates)
        assert greedy.cost_cents == 190
        solution = solve(index, query)
        assert solution.package_ids == (3,)
        assert solution.cost_cents == 150

    def test_partial_coverage_when_game_unstreamed(self) -> None:
        index = make_index(["2024-08", "2024-08"], {1: (500, None)}, {1: [0]})
        solution = solve(index, make_query())
        assert solution.package_ids == (1,)
        assert solution.coverage == 0.5
        assert solution.covered_mask == 0b01

    def test_empty_target_is_vacuously_covered(self) -> None:
        index = make_index(["2024-08"], {1: (100, None)}, {1: [0]})
        solution = solve(index, make_query(team_masks=(0,)))
        assert solution.package_ids == ()
        assert solution.cost_cents == 0
        assert solution.coverage == 1.0

    def test_nothing_eligible_gives_zero_coverage(self) -> None:
        index = make_index(["2024-08"], {1: (None, None)}, {1: [0]})
        solution = solve(index, make_query())
        assert solution.package_ids == ()
        assert solution.coverage == 0.0

    def test_min_packages_prefers_fewer_expensive_packages(self) -> None:
        # Only P1+P2 cover everything with two packages; the cheap trio needs
        # three. No two-package mix of cheap and expensive works.
        index = make_index(
            ["2024-08"] * 4,
            {1: (10000, None), 2: (10000, None), 3: (100, None), 4: (100, None), 5: (100, None)},
            {1: [0, 1], 2: [2, 3], 3: [0], 4: [1, 2], 5: [3]},
        )
        cheap = solve(index, make_query(objective="min_price"))
        assert cheap.package_ids == (3, 4, 5)
        assert cheap.cost_cents == 300
        few = solve(index, make_query(objective="min_packages"))
        assert few.package_ids == (1, 2)
        assert few.cost_cents == 20000

    def test_min_packages_breaks_ties_by_price(self) -> None:
        index = make_index(
            ["2024-08"] * 2,
            {1: (500, None), 2: (300, None), 3: (400, None)},
            {1: [0, 1], 2: [0, 1], 3: [0]},
        )
        solution = solve(index, make_query(objective="min_packages"))
        assert solution.package_ids == (2,)
        assert solution.cost_cents == 300

    def test_both_requirement_combines_two_packages(self) -> None:
        index = make_index(
            ["2024-08"],
            {1: (100, None), 2: (100, None)},
            live={1: [0]},
            highlights={2: [0]},
        )
        solution = solve(index, make_query(requirement="both"))
        assert solution.package_ids == (1, 2)
        assert solution.coverage == 1.0

    def test_both_requirement_ignores_unpairable_games(self) -> None:
        # Game 1 has live+highlights via two packages; game 2 only live.
        # The solver must not buy anything extra for game 2 and must report
        # coverage 0.5 honestly.
        index = make_index(
            ["2024-08", "2024-08"],
            {1: (100, None), 2: (100, None), 3: (5000, None)},
            live={1: [0], 3: [1]},
            highlights={2: [0]},
        )
        solution = solve(index, make_query(requirement="both"))
        assert solution.package_ids == (1, 2)
        assert solution.coverage == 0.5


def _brute_best(
    target: int, coverages: list[PackageCoverage], objective: Objective
) -> tuple[int, int] | None:
    """(count, cost) of the optimal full cover of the coverable subset."""
    coverable = 0
    for cov in coverages:
        coverable |= cov.live_mask
    effective = target & coverable
    if effective == 0:
        return None
    best_key: tuple[int, int] | None = None
    for r in range(len(coverages) + 1):
        for combo in itertools.combinations(coverages, r):
            covered = 0
            cost = 0
            for cov in combo:
                covered |= cov.live_mask
                assert cov.cost_cents is not None
                cost += cov.cost_cents
            if covered & effective != effective:
                continue
            key = (cost, r) if objective == "min_price" else (r, cost)
            if best_key is None or key < best_key:
                best_key = key
    assert best_key is not None  # effective is coverable by construction
    if objective == "min_price":
        return best_key[1], best_key[0]
    return best_key


class TestBruteForceCrossCheck:
    @pytest.mark.parametrize("seed", range(50))
    @pytest.mark.parametrize("objective", ["min_price", "min_packages"])
    def test_solver_matches_exhaustive_enumeration(self, seed: int, objective: Objective) -> None:
        rng = random.Random(seed)
        n_games = rng.randint(3, 10)
        n_packages = rng.randint(2, 8)
        months = [rng.choice(["2024-08", "2024-09", "2024-10"]) for _ in range(n_games)]
        packages: dict[int, tuple[int | None, int | None]] = {}
        live: dict[int, list[int]] = {}
        for pid in range(1, n_packages + 1):
            monthly = rng.choice([None, rng.randint(1, 50) * 100])
            yearly = rng.choice([None, rng.randint(1, 40) * 100])
            packages[pid] = (monthly, yearly)
            live[pid] = [bit for bit in range(n_games) if rng.random() < 0.4]
        index = make_index(months, packages, live)
        billing: Billing = rng.choice(["monthly_chained", "yearly", "flexible"])
        query = make_query(objective=objective, billing=billing)

        target, coverages = relevant_coverages(index, query)
        expected = _brute_best(target, coverages, objective)
        solution = solve(index, query)
        if expected is None:
            assert solution.package_ids == ()
            return
        count, cost = expected
        if objective == "min_price":
            assert solution.cost_cents == cost
        else:
            assert (len(solution.package_ids), solution.cost_cents) == (count, cost)


class TestExactFlag:
    def test_completed_search_marks_solution_exact(self) -> None:
        index = make_index(["2024-08", "2024-08"], {1: (500, None)}, {1: [0, 1]})
        assert solve(index, make_query()).exact is True

    def test_expired_time_budget_marks_solution_inexact(self, monkeypatch) -> None:
        """An already-expired budget forces the incumbent path.

        The instance must cost > 1024 search nodes (expiry is only checked
        every 1024th node): near-equal package prices and dense overlap keep
        the bounds from pruning early. The incumbent (greedy or better) is
        still returned, honestly flagged as not proven optimal.
        """
        monkeypatch.setattr("solver.setcover._TIME_BUDGET_S", -1.0)
        rng = random.Random(0)
        n_games, n_packages = 26, 40
        packages: dict[int, tuple[int | None, int | None]] = {
            pid: (1000 + rng.randint(0, 5), None) for pid in range(1, n_packages + 1)
        }
        live = {pid: [b for b in range(n_games) if rng.random() < 0.3] for pid in packages}
        index = make_index(["2024-08"] * n_games, packages, live)

        solution = solve(index, make_query())
        assert solution.exact is False
        assert solution.package_ids  # the incumbent is still returned
