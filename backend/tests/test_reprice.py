"""Tests for solver.reprice — post-hoc re-pricing of a chosen combination.

Core guarantee: the re-priced total is never above the sum of the static
``PackageCoverage.cost_cents`` (each package's assigned months are a subset
of its own coverage months). In the additive case (no yearly price) the
scheme is exact, verified by brute force over month-activation profiles.
"""

import itertools
import random

import pytest

from solver.reprice import covered_games_mask, drop_redundant, reprice_combination
from solver.setcover import relevant_coverages
from solver.types import Billing, Requirement

from .test_setcover import make_index, make_query


def _coverages(index, requirement: Requirement = "live", billing: Billing = "monthly_chained"):
    """Stage-1 coverages plus the index, for hand-built combinations."""
    query = make_query(requirement=requirement, billing=billing)
    target, coverages = relevant_coverages(index, query)
    return target, {cov.package.id: cov for cov in coverages}


class TestRepriceCombination:
    def test_shared_month_goes_to_the_cheaper_package(self) -> None:
        """The motivating example: A is only needed in August (B covers the
        September game cheaper), so A must not pay September."""
        index = make_index(
            ["2024-08", "2024-09"], {1: (1000, None), 2: (100, None)}, {1: [0, 1], 2: [1]}
        )
        _, by_id = _coverages(index)
        chosen = [by_id[1], by_id[2]]
        cost = reprice_combination(2, "live", "monthly_chained", 0b11, chosen, index.month_mask)
        assert cost == 1000 + 100  # A: Aug only; B: Sep
        assert cost < sum(c.cost_cents for c in chosen)  # static would be 2100

    def test_forced_unique_month_is_paid_regardless_of_price(self) -> None:
        index = make_index(
            ["2024-08", "2024-09"], {1: (9000, None), 2: (100, None)}, {1: [0, 1], 2: [0]}
        )
        _, by_id = _coverages(index)
        # Only package 1 covers the September game: it pays Sep, and August
        # goes to it too (already active would cost 9000 more; cheap B wins).
        cost = reprice_combination(
            2, "live", "monthly_chained", 0b11, [by_id[1], by_id[2]], index.month_mask
        )
        assert cost == 9000 + 100

    def test_already_active_package_is_preferred(self) -> None:
        """A need servable by an already-forced package adds no cost."""
        index = make_index(
            ["2024-08", "2024-08"], {1: (1000, None), 2: (100, None)}, {1: [0, 1], 2: [1]}
        )
        _, by_id = _coverages(index)
        # Game 0 forces package 1 in August; game 1 is then free for it.
        cost = reprice_combination(
            2, "live", "monthly_chained", 0b11, [by_id[1], by_id[2]], index.month_mask
        )
        assert cost == 1000  # package 2 is never activated

    def test_yearly_cap_makes_extra_months_free(self) -> None:
        """Once a package's chained months hit the yearly cap, further months
        cost 0 and are reused instead of activating another package."""
        index = make_index(
            ["2024-08", "2024-09", "2024-10"],
            {1: (1000, 100), 2: (150, None)},  # cap for 1: 12*100 = 1200
            {1: [0, 1, 2], 2: [2]},
        )
        _, by_id = _coverages(index)
        # Aug+Sep force package 1 -> 1200 (capped). October: marginal cost of
        # package 1 is 0 < 150, so package 2 stays unused.
        cost = reprice_combination(
            3, "live", "monthly_chained", 0b111, [by_id[1], by_id[2]], index.month_mask
        )
        assert cost == 1200

    def test_yearly_billing_is_flat_and_zero_need_packages_pay_nothing(self) -> None:
        index = make_index(
            ["2024-08", "2024-09"], {1: (None, 100), 2: (None, 100)}, {1: [0, 1], 2: [1]}
        )
        _, by_id = _coverages(index, billing="yearly")
        # Package 1 is forced for Aug and flat-priced, so Sep reuses it for
        # free; package 2 ends up with zero needs and must pay 0, not 1200.
        cost = reprice_combination(
            2, "live", "yearly", 0b11, [by_id[1], by_id[2]], index.month_mask
        )
        assert cost == 1200

    def test_both_requirement_charges_live_and_highlights_providers(self) -> None:
        index = make_index(
            ["2024-08"],
            {1: (500, None), 2: (300, None)},
            live={1: [0]},
            highlights={2: [0]},
        )
        _, by_id = _coverages(index, requirement="both")
        chosen = [by_id[1], by_id[2]]
        covered = covered_games_mask("both", chosen)
        assert covered == 0b1
        cost = reprice_combination(1, "both", "monthly_chained", covered, chosen, index.month_mask)
        assert cost == 500 + 300  # both halves needed, both packages pay August

    def test_both_requirement_ignores_unpairable_games(self) -> None:
        """A game whose highlights nobody offers generates no needs at all."""
        index = make_index(
            ["2024-08", "2024-09"],
            {1: (500, None)},
            live={1: [0, 1]},
            highlights={1: [0]},  # game 1 has live only -> unpairable
        )
        _, by_id = _coverages(index, requirement="both")
        chosen = [by_id[1]]
        covered = covered_games_mask("both", chosen)
        assert covered == 0b01
        cost = reprice_combination(2, "both", "monthly_chained", covered, chosen, index.month_mask)
        assert cost == 500  # August only; September's live-only game is free

    def test_uncovered_games_generate_no_needs(self) -> None:
        index = make_index(["2024-08", "2024-09"], {1: (700, None)}, {1: [0]})
        _, by_id = _coverages(index)
        # September's game is streamed by nobody: only August is charged.
        cost = reprice_combination(2, "live", "monthly_chained", 0b01, [by_id[1]], index.month_mask)
        assert cost == 700

    def test_empty_inputs_cost_nothing(self) -> None:
        index = make_index(["2024-08"], {1: (100, None)}, {1: [0]})
        _, by_id = _coverages(index)
        mm = index.month_mask
        assert reprice_combination(1, "live", "monthly_chained", 0, [by_id[1]], mm) == 0
        assert reprice_combination(1, "live", "monthly_chained", 0b1, [], mm) == 0

    @pytest.mark.parametrize("billing", ["monthly_chained", "yearly", "flexible"])
    def test_single_package_reprices_to_its_static_cost(self, billing: Billing) -> None:
        """Alone, a package's needs are exactly its covered games — the
        re-priced cost must equal the static cost (guards single-package
        Pareto points)."""
        index = make_index(
            ["2024-08", "2024-09", "2024-10"], {1: (400, 90), 2: (None, 50)}, {1: [0, 2], 2: [1]}
        )
        _, by_id = _coverages(index, billing=billing)
        for cov in by_id.values():
            covered = cov.live_mask
            assert (
                reprice_combination(3, "live", billing, covered, [cov], index.month_mask)
                == cov.cost_cents
            )


def _random_instance(seed: int):
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


class TestRepriceProperties:
    @pytest.mark.parametrize("seed", range(30))
    @pytest.mark.parametrize("requirement", ["live", "highlights", "both"])
    @pytest.mark.parametrize("billing", ["monthly_chained", "yearly", "flexible"])
    def test_never_above_static_and_deterministic(
        self, seed: int, requirement: Requirement, billing: Billing
    ) -> None:
        index = _random_instance(seed)
        query = make_query(requirement=requirement, billing=billing)
        _, coverages = relevant_coverages(index, query)
        if not coverages:
            return
        game_count = len(index.game_ids)
        covered = covered_games_mask(requirement, coverages)
        args = (game_count, requirement, billing, covered, coverages, index.month_mask)
        cost = reprice_combination(*args)
        assert cost <= sum(cov.cost_cents for cov in coverages)
        assert cost == reprice_combination(*args)  # deterministic


def _brute_reprice(
    monthly: dict[int, int],
    serve: dict[int, dict[str, int]],
    month_needs: dict[str, int],
) -> int:
    """Exact minimum for the additive case: enumerate every per-month subset
    of active packages; a profile is feasible when each month's needs are
    covered by its active packages."""
    pids = sorted(monthly)
    months = sorted(m for m, need in month_needs.items() if need)
    best: int | None = None
    for profile in itertools.product(range(1 << len(pids)), repeat=len(months)):
        cost = 0
        feasible = True
        for month, subset in zip(months, profile, strict=True):
            cover = 0
            for i, pid in enumerate(pids):
                if subset >> i & 1:
                    cover |= serve[pid][month]
                    cost += monthly[pid]
            if month_needs[month] & ~cover:
                feasible = False
                break
        if feasible and (best is None or cost < best):
            best = cost
    assert best is not None
    return best


class TestRepriceBruteForce:
    @pytest.mark.parametrize("seed", range(25))
    def test_additive_case_is_exact(self, seed: int) -> None:
        """Without yearly prices the cost is months*monthly (no cap), months
        decouple, and the per-month exact mini-cover must be globally exact."""
        rng = random.Random(seed)
        n_games = rng.randint(2, 6)
        n_packages = rng.randint(2, 4)
        month_pool = ["2024-08", "2024-09", "2024-10"][: rng.randint(1, 3)]
        months = [rng.choice(month_pool) for _ in range(n_games)]
        packages: dict[int, tuple[int | None, int | None]] = {}
        live: dict[int, list[int]] = {}
        for pid in range(1, n_packages + 1):
            packages[pid] = (rng.randint(1, 30) * 100, None)
            live[pid] = [bit for bit in range(n_games) if rng.random() < 0.5]
        index = make_index(months, packages, live)
        _, coverages = relevant_coverages(index, make_query())
        if not coverages:
            return
        covered = covered_games_mask("live", coverages)

        cost = reprice_combination(
            len(index.game_ids), "live", "monthly_chained", covered, coverages, index.month_mask
        )
        expected = _brute_reprice(
            {cov.package.id: cov.package.monthly_price_cents for cov in coverages},
            {
                cov.package.id: {
                    m: cov.live_mask & covered & mask for m, mask in index.month_mask.items()
                }
                for cov in coverages
            },
            {m: covered & mask for m, mask in index.month_mask.items()},
        )
        assert cost == expected


class TestDropRedundant:
    def test_no_redundancy_leaves_selection_unchanged(self) -> None:
        index = make_index(
            ["2024-08", "2024-08"], {1: (100, None), 2: (50, None)}, {1: [0], 2: [1]}
        )
        _, by_id = _coverages(index)
        chosen = [by_id[1], by_id[2]]
        kept, cost = drop_redundant(2, "live", "monthly_chained", chosen, index.month_mask)
        assert kept == chosen
        assert cost == 150

    def test_most_expensive_of_mutually_replaceable_pair_goes(self) -> None:
        # Both cover both games; either alone suffices, so the expensive one
        # must be dropped and the cheap one kept.
        index = make_index(
            ["2024-08", "2024-08"], {1: (500, None), 2: (100, None)}, {1: [0, 1], 2: [0, 1]}
        )
        _, by_id = _coverages(index)
        kept, cost = drop_redundant(
            2, "live", "monthly_chained", [by_id[1], by_id[2]], index.month_mask
        )
        assert [cov.package.id for cov in kept] == [2]
        assert cost == 100

    def test_removal_iterates_until_stable(self) -> None:
        index = make_index(
            ["2024-08"],
            {1: (300, None), 2: (200, None), 3: (100, None)},
            {1: [0], 2: [0], 3: [0]},
        )
        _, by_id = _coverages(index)
        kept, cost = drop_redundant(
            1, "live", "monthly_chained", [by_id[1], by_id[2], by_id[3]], index.month_mask
        )
        assert [cov.package.id for cov in kept] == [3]
        assert cost == 100

    def test_coverage_redundant_but_cost_useful_package_stays(self) -> None:
        """B is a coverage subset of A but takes over September, so removing
        it would raise the re-priced total from 600 to 1000 — it must stay."""
        index = make_index(
            ["2024-08", "2024-09"], {1: (500, None), 2: (100, None)}, {1: [0, 1], 2: [1]}
        )
        _, by_id = _coverages(index)
        kept, cost = drop_redundant(
            2, "live", "monthly_chained", [by_id[1], by_id[2]], index.month_mask
        )
        assert [cov.package.id for cov in kept] == [1, 2]
        assert cost == 600
