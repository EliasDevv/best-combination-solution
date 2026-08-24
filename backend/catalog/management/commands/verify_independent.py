"""Independently verify compare results against an ILP built straight from the CSVs.

This command deliberately does NOT reuse the production pipeline. The
independent path reads the CSVs with pandas (no ``import_dataset``, no ORM,
no ``BitIndex``), determines target games with plain DataFrame filters,
re-implements the ``monthly_chained`` pricing model from its README
definition, and solves the set cover exactly with an ILP (PuLP + CBC). The
single shared component is ``catalog.normalize.normalize_team_name`` —
without it the two paths could not agree on team identity.

The pipeline path is the real one: ``BitIndex`` from the database via the
selectors bridge, static optimum via ``solver.setcover``, final result via
the ``solver.compare`` facade (which post-hoc re-prices, see README).

Both paths run the four README benchmark queries with requirement=live and
requirement=both. Divergences are localized stage by stage: target game ids
first, then coverable games, then per-package static costs, then the
optimum. The command exits non-zero on the first real divergence.

Slow by design (seconds, CBC solves ~17k constraints for the all-teams/both
query) — this is a verifier, not production code. Requires the dev
dependencies ``pandas`` and ``pulp``.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pulp
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.normalize import normalize_team_name
from catalog.selectors import build_index_from_db
from solver.compare import compare
from solver.index import BitIndex, warm_index
from solver.setcover import relevant_coverages, solve_reduced
from solver.types import Objective, PackageCoverage, Query, Requirement

# The four reference queries from the README benchmark table.
VERIFY_QUERIES: list[dict[str, Any]] = [
    {
        "label": "RB Leipzig (all games)",
        "teams": ["RB Leipzig"],
        "objective": "min_price",
    },
    {
        "label": "Hatayspor + Deutschland + RB Leipzig + Real Madrid",
        "teams": ["Hatayspor", "Deutschland", "RB Leipzig", "Real Madrid"],
        "objective": "min_price",
    },
    {
        "label": "All teams, fewest services",
        "teams": [],
        "objective": "min_packages",
    },
    {
        "label": "Oxford United + Los Angeles FC + AS Rom",
        "teams": ["Oxford United", "Los Angeles FC", "AS Rom"],
        "objective": "min_price",
    },
]

REQUIREMENTS: tuple[Requirement, ...] = ("live", "both")

_TRUTHY = frozenset({"1", "true", "True"})


# --------------------------------------------------------------------------
# Independent path: pandas + ILP, no pipeline code
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CsvData:
    games: pd.DataFrame  # id, starts_at, month, home_norm, away_norm, tournament_name
    offers: pd.DataFrame  # game_id, package_id, live, highlights
    prices: dict[int, tuple[int | None, int | None]]  # id -> (monthly, yearly_monthly)


@dataclass(frozen=True, slots=True)
class IndependentResult:
    target_ids: frozenset[int]
    coverable_ids: frozenset[int]
    package_costs: dict[int, int]  # static monthly_chained cost per relevant package
    package_ids: tuple[int, ...]
    cost_cents: int


def _load_csvs(directory: Path) -> CsvData:
    def _read(name: str) -> pd.DataFrame:
        path = directory / name
        if not path.exists():
            raise CommandError(f"CSV not found: {path}")
        return pd.read_csv(path, encoding="utf-8-sig")

    games = _read("bc_game.csv")
    packages = _read("bc_streaming_package.csv")
    offers = _read("bc_streaming_offer.csv")

    games["starts_at"] = pd.to_datetime(games["starts_at"])
    games["month"] = games["starts_at"].dt.strftime("%Y-%m")
    games["home_norm"] = games["team_home"].map(lambda n: normalize_team_name(str(n)))
    games["away_norm"] = games["team_away"].map(lambda n: normalize_team_name(str(n)))

    offers = offers.rename(columns={"streaming_package_id": "package_id"})
    for flag in ("live", "highlights"):
        offers[flag] = offers[flag].astype(str).str.strip().isin(_TRUTHY)
    # replicate the import's referential cleanup naively: drop offers pointing
    # at games/packages absent from the CSVs (the dataset contains such rows)
    offers = offers[
        offers["game_id"].isin(set(games["id"])) & offers["package_id"].isin(set(packages["id"]))
    ].drop_duplicates()

    prices: dict[int, tuple[int | None, int | None]] = {}
    for row in packages.itertuples():
        monthly = None if pd.isna(row.monthly_price_cents) else int(row.monthly_price_cents)
        yearly = (
            None
            if pd.isna(row.monthly_price_yearly_subscription_in_cents)
            else int(row.monthly_price_yearly_subscription_in_cents)
        )
        prices[int(row.id)] = (monthly, yearly)
    return CsvData(games=games, offers=offers, prices=prices)


def _chained_cost(monthly: int | None, yearly_monthly: int | None, months: int) -> int | None:
    """README definition of monthly_chained: min(months x monthly, 12 x yearly_monthly);
    yearly-only packages fall back to the yearly price; None = not bookable."""
    options = []
    if monthly is not None:
        options.append(months * monthly)
    if yearly_monthly is not None:
        options.append(12 * yearly_monthly)
    return min(options) if options else None


def _solve_cover(
    needs: dict[tuple[str, int], frozenset[int]],
    weights: dict[int, int],
    count_cap: int | None = None,
) -> list[int]:
    """Exact weighted set cover via ILP: one binary per package, one >=1
    constraint per need, minimize the weighted sum."""
    usable = sorted({pid for providers in needs.values() for pid in providers})
    prob = pulp.LpProblem("verify_independent", pulp.LpMinimize)
    x = {pid: pulp.LpVariable(f"x_{pid}", cat="Binary") for pid in usable}
    prob += pulp.lpSum(weights[pid] * x[pid] for pid in usable)
    for providers in needs.values():
        prob += pulp.lpSum(x[pid] for pid in providers) >= 1
    if count_cap is not None:
        prob += pulp.lpSum(x.values()) <= count_cap
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise CommandError(f"CBC did not reach Optimal: {pulp.LpStatus[status]}")
    return sorted(pid for pid in usable if (x[pid].value() or 0) > 0.5)


def independent_solve(
    data: CsvData,
    teams: list[str],
    requirement: Requirement,
    objective: Objective,
    date_from: date | None = None,
    date_to: date | None = None,
    tournaments: list[str] | None = None,
) -> IndependentResult:
    games = data.games
    mask = pd.Series(True, index=games.index)
    if teams:
        wanted = {normalize_team_name(t) for t in teams}
        mask &= games["home_norm"].isin(wanted) | games["away_norm"].isin(wanted)
    if date_from is not None:
        mask &= games["starts_at"].dt.date >= date_from
    if date_to is not None:
        mask &= games["starts_at"].dt.date <= date_to
    if tournaments:
        mask &= games["tournament_name"].isin(set(tournaments))
    target = games[mask]
    target_ids = frozenset(int(g) for g in target["id"])
    month_of = {int(row.id): row.month for row in target.itertuples()}

    offers = data.offers[data.offers["game_id"].isin(target_ids)]

    # static cost per package: distinct months of its own clipped coverage —
    # the target games it can serve under the requirement ("both" counts a
    # game it serves either way, even if the other half comes from elsewhere)
    if requirement == "live":
        relevant = offers[offers["live"]]
    elif requirement == "highlights":
        relevant = offers[offers["highlights"]]
    else:
        relevant = offers[offers["live"] | offers["highlights"]]
    package_costs: dict[int, int] = {}
    for pid, game_ids in relevant.groupby("package_id")["game_id"]:
        months = len({month_of[int(g)] for g in game_ids})
        monthly, yearly_monthly = data.prices[int(pid)]
        cost = _chained_cost(monthly, yearly_monthly, months)
        if cost is not None:
            package_costs[int(pid)] = cost

    # needs: per game, which bookable packages can serve it; with "both" the
    # live and highlights needs are separate and may be met by different
    # packages; games nobody can serve (in the required way) drop out of the
    # optimization but stay in the denominator of the coverage rate
    bookable = offers[offers["package_id"].isin(package_costs)]
    as_set = lambda s: frozenset(int(v) for v in s)  # noqa: E731
    live_prov = bookable[bookable["live"]].groupby("game_id")["package_id"].agg(as_set)
    hl_prov = bookable[bookable["highlights"]].groupby("game_id")["package_id"].agg(as_set)
    needs: dict[tuple[str, int], frozenset[int]] = {}
    if requirement == "live":
        coverable_ids = frozenset(int(g) for g in live_prov.index)
        needs = {("live", g): live_prov[g] for g in coverable_ids}
    elif requirement == "highlights":
        coverable_ids = frozenset(int(g) for g in hl_prov.index)
        needs = {("highlights", g): hl_prov[g] for g in coverable_ids}
    else:
        coverable_ids = frozenset(int(g) for g in live_prov.index) & frozenset(
            int(g) for g in hl_prov.index
        )
        for g in coverable_ids:
            needs[("live", g)] = live_prov[g]
            needs[("highlights", g)] = hl_prov[g]

    if not needs:
        return IndependentResult(target_ids, coverable_ids, package_costs, (), 0)

    if objective == "min_packages":
        # two-stage: minimal package count first, then cheapest at that count
        fewest = _solve_cover(needs, dict.fromkeys(package_costs, 1))
        chosen = _solve_cover(needs, package_costs, count_cap=len(fewest))
    else:
        chosen = _solve_cover(needs, package_costs)
    total = sum(package_costs[pid] for pid in chosen)
    return IndependentResult(target_ids, coverable_ids, package_costs, tuple(chosen), total)


# --------------------------------------------------------------------------
# Pipeline path + comparison
# --------------------------------------------------------------------------


def _bits_to_ids(mask: int, index: BitIndex) -> frozenset[int]:
    ids = []
    while mask:
        low = mask & -mask
        ids.append(index.game_ids[low.bit_length() - 1])
        mask ^= low
    return frozenset(ids)


def _pipeline_coverable(
    requirement: Requirement, coverages: list[PackageCoverage], index: BitIndex
) -> frozenset[int]:
    live_any = 0
    hl_any = 0
    for cov in coverages:
        live_any |= cov.live_mask
        hl_any |= cov.highlight_mask
    if requirement == "live":
        mask = live_any
    elif requirement == "highlights":
        mask = hl_any
    else:
        mask = live_any & hl_any
    return _bits_to_ids(mask, index)


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} EUR"


def _sample(ids: frozenset[int], limit: int = 10) -> str:
    ordered = sorted(ids)
    suffix = ", ..." if len(ordered) > limit else ""
    return f"[{', '.join(str(i) for i in ordered[:limit])}{suffix}]"


class Command(BaseCommand):
    help = (
        "Cross-check the compare pipeline against an independent pandas+ILP "
        "solver built straight from the CSVs (slow; dev-only verifier)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            default=settings.REPO_ROOT / "data",
            help="Directory containing the CSV files (default: <repo>/data).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        data = _load_csvs(options["path"])
        try:
            index = warm_index(build_index_from_db)
        except Exception:
            self.stderr.write("Could not build the index (empty database?); run import_dataset.")
            raise

        failures: list[str] = []
        for spec in VERIFY_QUERIES:
            for requirement in REQUIREMENTS:
                label = f"{spec['label']} — requirement={requirement}, {spec['objective']}"
                self.stdout.write(f"\n=== {label} ===")
                divergence = self._verify_one(data, index, spec, requirement)
                if divergence:
                    failures.append(f"{label}: {divergence}")
                    self.stdout.write(self.style.ERROR(f"  DIVERGENCE: {divergence}"))

        self.stdout.write("")
        if failures:
            raise CommandError(f"{len(failures)} of 8 checks diverged — see above.")
        self.stdout.write(self.style.SUCCESS("All 8 checks passed: ILP and pipeline agree."))

    def _verify_one(
        self,
        data: CsvData,
        index: BitIndex,
        spec: dict[str, Any],
        requirement: Requirement,
    ) -> str | None:
        """Run both paths for one query. Returns the first divergence, or None.

        The checks are ordered so a failure is already localized: target game
        ids -> coverable games -> per-package static costs -> optimum.
        """
        objective: Objective = spec["objective"]
        ind = independent_solve(data, spec["teams"], requirement, objective)

        team_masks: tuple[int, ...] = ()
        if spec["teams"]:
            team_masks = tuple(
                index.team_mask.get(normalize_team_name(team), 0) for team in spec["teams"]
            )
        query = Query(
            team_masks=team_masks,
            date_from=None,
            date_to=None,
            requirement=requirement,
            objective=objective,
            billing="monthly_chained",
        )
        target_mask, coverages = relevant_coverages(index, query)
        static = solve_reduced(len(index.game_ids), query, target_mask, coverages)
        facade = compare(index, query)

        # 1) target games must be identical
        pipe_target = _bits_to_ids(target_mask, index)
        self.stdout.write(
            f"  target games     ILP {len(ind.target_ids)} | pipeline {len(pipe_target)}"
        )
        if ind.target_ids != pipe_target:
            only_ilp = ind.target_ids - pipe_target
            only_pipe = pipe_target - ind.target_ids
            return (
                f"target game ids differ: only-ILP {_sample(only_ilp)}, "
                f"only-pipeline {_sample(only_pipe)}"
            )

        # 2) coverable games must be identical
        pipe_coverable = _pipeline_coverable(requirement, coverages, index)
        rate = len(ind.coverable_ids) / len(ind.target_ids) if ind.target_ids else 1.0
        self.stdout.write(
            f"  coverable games  ILP {len(ind.coverable_ids)} | pipeline {len(pipe_coverable)}"
            f"  (coverage {rate:.1%})"
        )
        if ind.coverable_ids != pipe_coverable:
            only_ilp = ind.coverable_ids - pipe_coverable
            only_pipe = pipe_coverable - ind.coverable_ids
            return (
                f"coverable games differ: only-ILP {_sample(only_ilp)}, "
                f"only-pipeline {_sample(only_pipe)}"
            )

        # 3) static per-package costs must be identical
        pipe_costs = {cov.package.id: cov.cost_cents for cov in coverages}
        if ind.package_costs != pipe_costs:
            diffs = []
            for pid in sorted(set(ind.package_costs) | set(pipe_costs)):
                a, b = ind.package_costs.get(pid), pipe_costs.get(pid)
                if a != b:
                    diffs.append(f"package {pid}: ILP {a} vs pipeline {b}")
            return f"per-package static costs differ: {'; '.join(diffs[:5])}"
        self.stdout.write(f"  package costs    {len(pipe_costs)} packages, all identical")

        # 4) the static optimum must be identical (facade re-pricing comes later)
        if objective == "min_packages":
            ilp_key = (len(ind.package_ids), ind.cost_cents)
            pipe_key = (len(static.package_ids), static.cost_cents)
            self.stdout.write(
                f"  static optimum   ILP {ilp_key[0]} pkgs / {_eur(ilp_key[1])}"
                f" | pipeline {pipe_key[0]} pkgs / {_eur(pipe_key[1])}"
            )
            if ilp_key != pipe_key:
                if not static.exact:
                    return (
                        f"(package count, cost) differ: ILP {ilp_key} vs pipeline {pipe_key} — "
                        "pipeline hit its time budget (exact=False), ILP result is the optimum"
                    )
                return f"(package count, cost) differ: ILP {ilp_key} vs pipeline {pipe_key}"
        else:
            self.stdout.write(
                f"  static optimum   ILP {_eur(ind.cost_cents)}"
                f" | pipeline {_eur(static.cost_cents)}"
            )
            if ind.cost_cents != static.cost_cents:
                if not static.exact:
                    return (
                        f"optimum differs: ILP {ind.cost_cents} vs pipeline "
                        f"{static.cost_cents} — pipeline hit its time budget "
                        "(exact=False), ILP result is the optimum"
                    )
                return f"optimum differs: ILP {ind.cost_cents} vs pipeline {static.cost_cents}"
        if not static.exact:
            self.stdout.write(
                self.style.WARNING("  note: pipeline exact=False, but values agree anyway")
            )

        # 5) package sets: may differ at equal price — then both are optimal
        if set(ind.package_ids) == set(static.package_ids):
            self.stdout.write(f"  packages         identical: {list(ind.package_ids)}")
        else:
            self.stdout.write(
                f"  packages         price tie, both optimal: ILP {list(ind.package_ids)}"
                f" | pipeline {list(static.package_ids)}"
            )

        # 6) facade result (informational): post-hoc re-pricing may undercut
        # the static optimum, never exceed it (see README design decisions)
        delta = facade.solution.cost_cents - static.cost_cents
        note = "= static" if delta == 0 else f"re-priced {_eur(-delta)} below static"
        self.stdout.write(
            f"  facade final     {list(facade.solution.package_ids)}, "
            f"{_eur(facade.solution.cost_cents)} ({note})"
        )
        if facade.solution.cost_cents > static.cost_cents:
            return (
                f"facade re-priced ABOVE the static optimum: "
                f"{facade.solution.cost_cents} > {static.cost_cents}"
            )
        return None
