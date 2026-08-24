from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Requirement = Literal["live", "highlights", "both"]
Objective = Literal["min_price", "min_packages"]
Billing = Literal["monthly_chained", "yearly", "flexible"]


@dataclass(frozen=True, slots=True)
class PackageInfo:
    """A streaming package's identity and its two price points."""

    id: int
    name: str
    # None = not bookable at that interval, never free
    monthly_price_cents: int | None
    yearly_monthly_price_cents: int | None


@dataclass(frozen=True, slots=True)
class GameMeta:
    """Display data for one game, carried alongside its bit for the response."""

    id: int
    team_home: str
    team_away: str
    starts_at: datetime
    tournament_name: str


@dataclass(frozen=True, slots=True)
class Query:
    """One compare request, already resolved against the index.

    Tournament filters are pre-intersected into ``team_masks`` by the caller,
    so the solver never learns what a tournament is.
    """

    team_masks: tuple[int, ...]  # empty = all games
    date_from: date | None
    date_to: date | None
    requirement: Requirement
    objective: Objective
    billing: Billing


@dataclass(frozen=True, slots=True)
class PackageCoverage:
    """A package clipped to one query's target, with its price for that target."""

    package: PackageInfo
    live_mask: int
    highlight_mask: int
    cost_cents: int | None  # None = not bookable under the query's billing


@dataclass(frozen=True, slots=True)
class Solution:
    """A chosen combination: which packages, what it costs, how much it covers.

    ``coverage`` is measured against the full target including games nobody
    streams, so it can be below 1.0 even when the answer is optimal.
    """

    package_ids: tuple[int, ...]
    cost_cents: int
    covered_mask: int
    coverage: float
    exact: bool = True  # False = time budget expired, best found so far


@dataclass(frozen=True, slots=True)
class ParetoPoint:
    """One rung on the coverage/price front: this much coverage, at this price."""

    coverage: float
    cost_cents: int
    package_ids: tuple[int, ...]
