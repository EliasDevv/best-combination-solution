import hashlib
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from catalog import selectors, services
from catalog.normalize import normalize_team_name
from catalog.selectors import build_index_from_db
from solver.compare import compare as run_compare
from solver.index import BitIndex, get_index, warm_index
from solver.pricing import months_needed, package_cost_cents
from solver.types import ParetoPoint, Query, Solution

from .serializers import (
    COMPARE_DEFAULTS,
    CompareRequestSerializer,
    SavedSearchSerializer,
)

logger = logging.getLogger(__name__)


def normalize_compare_params(validated: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and sort lists so equivalent requests share one cache key."""
    params = {**COMPARE_DEFAULTS, **validated}
    params["teams"] = sorted(set(params["teams"]))
    params["tournaments"] = sorted(set(params.get("tournaments") or []))
    params["date_from"] = params["date_from"].isoformat() if params["date_from"] else None
    params["date_to"] = params["date_to"].isoformat() if params["date_to"] else None
    return params


def compare_cache_key(params: dict[str, Any]) -> str:
    # sha256 of the normalized body; params must come from normalize_compare_params
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"compare:v1:{digest}"


def _iter_bits(mask: int) -> Iterator[int]:
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _build_query(index: BitIndex, params: dict[str, Any]) -> Query:
    """Resolve normalized request params against the index.

    Unknown team names resolve to mask 0 (they contribute no games). A
    tournament filter is pre-intersected into the team masks so the solver's
    ``Query`` stays tournament-agnostic.
    """
    if params["tournaments"]:
        tournament_filter = 0
        for name in params["tournaments"]:
            tournament_filter |= index.tournament_mask.get(name, 0)
    else:
        tournament_filter = (1 << len(index.game_ids)) - 1

    if params["teams"]:
        team_masks = tuple(
            index.team_mask.get(normalize_team_name(team), 0) & tournament_filter
            for team in params["teams"]
        )
    elif params["tournaments"]:
        team_masks = (tournament_filter,)
    else:
        team_masks = ()  # all games

    return Query(
        team_masks=team_masks,
        date_from=date.fromisoformat(params["date_from"]) if params["date_from"] else None,
        date_to=date.fromisoformat(params["date_to"]) if params["date_to"] else None,
        requirement=params["requirement"],
        objective=params["objective"],
        billing=params["billing"],
    )


def _build_payload(
    index: BitIndex,
    query: Query,
    target: int,
    solution: Solution,
    pareto: tuple[ParetoPoint, ...],
) -> dict[str, Any]:
    """Assemble the compare response from pure index data (no DB reads).

    ``live_idx``/``highlight_idx`` are indices into the returned ``games``
    array. The package list includes every package touching the target —
    even ones that are unbookable (``cost_cents: null``) or useless for the
    requirement — because the comparison table wants the full ranking.
    Per-package ``cost_cents`` is deliberately the *standalone* (static)
    price — what the package costs booked alone for its months — while the
    combination totals are re-priced (see ``solver.reprice``), so the
    combination can legitimately be cheaper than the sum of the table cells.
    """
    bit_to_idx: dict[int, int] = {}
    games: list[dict[str, Any]] = []
    for idx, bit in enumerate(_iter_bits(target)):
        bit_to_idx[bit] = idx
        meta = index.game_meta[bit]
        games.append(
            {
                "id": meta.id,
                "home": meta.team_home,
                "away": meta.team_away,
                "starts_at": meta.starts_at.isoformat().replace("+00:00", "Z"),
                "tournament": meta.tournament_name,
            }
        )

    packages: list[dict[str, Any]] = []
    for package_id, info in index.packages.items():
        live = index.live_mask[package_id] & target
        highlights = index.highlight_mask[package_id] & target
        if live | highlights == 0:
            continue
        if query.requirement == "live":
            relevant = live
        elif query.requirement == "highlights":
            relevant = highlights
        else:
            relevant = live | highlights
        # Cost basis: the months of the package's requirement-relevant
        # coverage (matching the solver); packages useless for the
        # requirement are priced over everything they offer instead.
        basis = relevant or (live | highlights)
        months = months_needed(
            frozenset(m for m, m_mask in index.month_mask.items() if basis & m_mask)
        )
        packages.append(
            {
                "id": package_id,
                "name": info.name,
                "live_idx": [bit_to_idx[b] for b in _iter_bits(live)],
                "highlight_idx": [bit_to_idx[b] for b in _iter_bits(highlights)],
                "cost_cents": package_cost_cents(info, months, query.billing),
            }
        )

    return {
        "games": games,
        "packages": packages,
        "best_combination": {
            "package_ids": list(solution.package_ids),
            "cost_cents": solution.cost_cents,
            "coverage": solution.coverage,
            "exact": solution.exact,
        },
        "pareto": [
            {
                "coverage": point.coverage,
                "cost_cents": point.cost_cents,
                "package_ids": list(point.package_ids),
            }
            for point in pareto
        ],
    }


@api_view(["GET"])
def teams(request: Request) -> Response:
    """GET /api/teams?q= — team name autocomplete."""
    query = request.query_params.get("q", "")
    names = selectors.search_team_names(query) if query else []
    return Response({"teams": names})


@api_view(["GET"])
def tournaments(request: Request) -> Response:
    """GET /api/tournaments — all tournament names."""
    return Response({"tournaments": selectors.list_tournaments()})


def _record_search(params: dict[str, Any], payload: dict[str, Any]) -> None:
    """Bonus bookkeeping — must never break the response.

    The result is already computed (and cached), so a failing DB write is
    only worth a log line.
    """
    try:
        services.record_search(params, payload["best_combination"])
    except Exception:
        logger.exception("failed to record saved search")


@api_view(["POST"])
def compare(request: Request) -> Response:
    """POST /api/compare — main endpoint: ranking + best combination."""
    serializer = CompareRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    params = normalize_compare_params(serializer.validated_data)

    key = compare_cache_key(params)
    cached = cache.get(key)
    if cached is not None:
        # A cache hit is still a search the user made: record it here too,
        # otherwise clearing the history hides every query whose response is
        # still cached (24h) until the entry expires.
        _record_search(params, cached)
        return Response(cached)

    try:
        index = get_index()
    except RuntimeError:
        # First request after process start: build the index now. warm_index
        # is lock-protected and idempotent, so concurrent requests build once.
        index = warm_index(build_index_from_db)

    query = _build_query(index, params)
    result = run_compare(index, query)
    payload = _build_payload(index, query, result.target_mask, result.solution, result.pareto)
    # Typos must not fail silently: name the teams that matched nothing.
    payload["unknown_teams"] = [
        team for team in params["teams"] if normalize_team_name(team) not in index.team_mask
    ]

    cache.set(key, payload, timeout=settings.COMPARE_CACHE_TTL_SECONDS)
    _record_search(params, payload)
    return Response(payload)


@api_view(["GET", "DELETE"])
def searches(request: Request) -> Response:
    """GET /api/searches — recently saved searches (bonus feature).

    DELETE clears the whole history; like the single-entry delete it is
    idempotent and answers 204 even when there was nothing to remove.
    """
    if request.method == "DELETE":
        services.clear_searches()
        return Response(status=204)
    queryset = selectors.list_saved_searches()
    return Response({"searches": SavedSearchSerializer(queryset, many=True).data})


@api_view(["DELETE"])
def search_detail(request: Request, search_id: uuid.UUID) -> Response:
    """DELETE /api/searches/<id> — drop one entry from the recent list.

    Idempotent: deleting an already-removed entry is still a 204, so a double
    click from the UI does not surface an error.
    """
    services.delete_search(search_id)
    return Response(status=204)
