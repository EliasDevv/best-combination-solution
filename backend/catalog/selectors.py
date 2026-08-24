"""Read-only query helpers (the only place the API reads the database).

Views must not contain ORM logic; they call these selectors. The solver never
calls them either — it works exclusively on the in-memory ``BitIndex``.
"""

import re
from typing import TYPE_CHECKING

from django.db.models import QuerySet

from .models import Game, SavedSearch, StreamingOffer, StreamingPackage
from .normalize import normalize_team_name, search_fold

_WORD_SPLIT_RE = re.compile(r"[\s.\-]+")

if TYPE_CHECKING:
    from solver.index import BitIndex


def search_team_names(query: str, limit: int = 20) -> list[str]:
    """Distinct team names (home or away) matching ``query``, for autocomplete.

    Ranked in three tiers, each alphabetical: whole-name prefix, then
    word prefix (words split at spaces/dots/hyphens, so "st" hits
    "FC St. Pauli"), then plain substring. Later tiers only fill whatever
    room the limit leaves. Matching is case- and diacritic-insensitive
    ("munchen" finds "München"), done in Python because the team list is
    tiny and the database can't fold diacritics.
    """
    home = Game.objects.values_list("team_home", flat=True).distinct()
    away = Game.objects.values_list("team_away", flat=True).distinct()
    folded_query = search_fold(query)
    tiers: tuple[list[str], list[str], list[str]] = ([], [], [])
    for name in set(home) | set(away):
        folded = search_fold(name)
        if folded.startswith(folded_query):
            tiers[0].append(name)
        elif any(word.startswith(folded_query) for word in _WORD_SPLIT_RE.split(folded)):
            tiers[1].append(name)
        elif folded_query in folded:
            tiers[2].append(name)
    ranked = [name for tier in tiers for name in sorted(tier, key=lambda n: (search_fold(n), n))]
    return ranked[:limit]


def list_tournaments() -> list[str]:
    """All distinct tournament names, sorted."""
    return list(
        Game.objects.order_by("tournament_name")
        .values_list("tournament_name", flat=True)
        .distinct()
    )


def list_saved_searches(limit: int = 50) -> QuerySet[SavedSearch]:
    return SavedSearch.objects.all()[:limit]


def build_index_from_db() -> "BitIndex":
    """Assemble solver input from the database and build the BitIndex.

    This is the single bridge between Django and the solver package: it reads
    the ORM, converts rows into plain data, and hands them to
    ``solver.index.build_index``. Called once per process via ``warm_index``,
    lazily on the first compare request. Team names are normalized
    here (the solver knows nothing about normalization); the raw display
    names ride along for the response path. The model field
    ``monthly_price_yearly_subscription_in_cents`` is renamed to the solver's
    ``yearly_monthly_price_cents`` here and nowhere else.
    """
    from solver.index import build_index

    games = [
        {
            "id": row["id"],
            "team_home": normalize_team_name(row["team_home"]),
            "team_away": normalize_team_name(row["team_away"]),
            "team_home_display": row["team_home"],
            "team_away_display": row["team_away"],
            "starts_at": row["starts_at"],
            "tournament_name": row["tournament_name"],
        }
        for row in Game.objects.values(
            "id", "team_home", "team_away", "starts_at", "tournament_name"
        )
    ]
    packages = [
        {
            "id": row["id"],
            "name": row["name"],
            "monthly_price_cents": row["monthly_price_cents"],
            "yearly_monthly_price_cents": row["monthly_price_yearly_subscription_in_cents"],
        }
        for row in StreamingPackage.objects.values(
            "id", "name", "monthly_price_cents", "monthly_price_yearly_subscription_in_cents"
        )
    ]
    offers = [
        {
            "game_id": row["game_id"],
            "package_id": row["streaming_package_id"],
            "live": row["live"],
            "highlights": row["highlights"],
        }
        for row in StreamingOffer.objects.values(
            "game_id", "streaming_package_id", "live", "highlights"
        )
    ]
    return build_index(games=games, packages=packages, offers=offers)
