"""In-memory bitmask index over the whole dataset, built once per process."""

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .types import GameMeta, PackageInfo


@dataclass(frozen=True, slots=True)
class BitIndex:
    """Bit i in every mask refers to game_ids[i]; games sorted by (starts_at, id)."""

    game_ids: tuple[int, ...]
    game_pos: Mapping[int, int]
    game_month: tuple[str, ...]
    game_starts: tuple[datetime, ...]
    game_meta: tuple[GameMeta, ...]
    team_mask: Mapping[str, int]
    tournament_mask: Mapping[str, int]
    month_mask: Mapping[str, int]
    live_mask: Mapping[int, int]
    highlight_mask: Mapping[int, int]
    packages: Mapping[int, PackageInfo]


def build_index(
    games: Sequence[Mapping[str, Any]],
    packages: Sequence[Mapping[str, Any]],
    offers: Sequence[Mapping[str, Any]],
) -> BitIndex:
    """Compile the whole dataset into the bitmask index the solver runs on.

    Takes plain mappings, never ORM objects — this is what keeps the package
    free of Django (``catalog.selectors.build_index_from_db`` does the
    conversion). Games are sorted by ``(starts_at, id)`` and each one claims
    the bit at its position, which is what makes a date range a contiguous
    bit run that ``setcover`` can bisect. Team, tournament and month masks are
    precomputed over the same bit space, as are one live and one highlights
    mask per package.

    ``team_home``/``team_away`` are used as mask keys verbatim, so the caller
    must pass names already normalized; the raw display names ride along in
    ``team_home_display``/``team_away_display`` for the response path.

    Raises ``ValueError`` if an offer references a game or package that is not
    in the dataset — a silently dropped offer would understate coverage.
    """

    def _as_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    ordered = sorted(
        ({**row, "starts_at": _as_datetime(row["starts_at"])} for row in games),
        key=lambda row: (row["starts_at"], row["id"]),
    )

    game_ids: list[int] = []
    game_month: list[str] = []
    game_starts: list[datetime] = []
    game_meta: list[GameMeta] = []
    game_pos: dict[int, int] = {}
    team_mask: dict[str, int] = {}
    tournament_mask: dict[str, int] = {}
    month_mask: dict[str, int] = {}

    for pos, row in enumerate(ordered):
        bit = 1 << pos
        starts_at: datetime = row["starts_at"]
        month = f"{starts_at:%Y-%m}"
        game_ids.append(row["id"])
        game_pos[row["id"]] = pos
        game_month.append(month)
        game_starts.append(starts_at)
        game_meta.append(
            GameMeta(
                id=row["id"],
                team_home=row.get("team_home_display", row["team_home"]),
                team_away=row.get("team_away_display", row["team_away"]),
                starts_at=starts_at,
                tournament_name=row["tournament_name"],
            )
        )
        tournament = row["tournament_name"]
        team_mask[row["team_home"]] = team_mask.get(row["team_home"], 0) | bit
        team_mask[row["team_away"]] = team_mask.get(row["team_away"], 0) | bit
        tournament_mask[tournament] = tournament_mask.get(tournament, 0) | bit
        month_mask[month] = month_mask.get(month, 0) | bit

    package_infos: dict[int, PackageInfo] = {}
    live_mask: dict[int, int] = {}
    highlight_mask: dict[int, int] = {}
    for pkg_row in packages:
        pid = pkg_row["id"]
        package_infos[pid] = PackageInfo(
            id=pid,
            name=pkg_row["name"],
            monthly_price_cents=pkg_row["monthly_price_cents"],
            yearly_monthly_price_cents=pkg_row["yearly_monthly_price_cents"],
        )
        live_mask[pid] = 0
        highlight_mask[pid] = 0

    for offer_row in offers:
        game_id, package_id = offer_row["game_id"], offer_row["package_id"]
        if game_id not in game_pos:
            raise ValueError(f"offer references unknown game id {game_id}")
        if package_id not in package_infos:
            raise ValueError(f"offer references unknown package id {package_id}")
        bit = 1 << game_pos[game_id]
        if offer_row["live"]:
            live_mask[package_id] |= bit
        if offer_row["highlights"]:
            highlight_mask[package_id] |= bit

    return BitIndex(
        game_ids=tuple(game_ids),
        game_pos=MappingProxyType(game_pos),
        game_month=tuple(game_month),
        game_starts=tuple(game_starts),
        game_meta=tuple(game_meta),
        team_mask=MappingProxyType(team_mask),
        tournament_mask=MappingProxyType(tournament_mask),
        month_mask=MappingProxyType(month_mask),
        live_mask=MappingProxyType(live_mask),
        highlight_mask=MappingProxyType(highlight_mask),
        packages=MappingProxyType(package_infos),
    )


_lock = threading.Lock()
_index: BitIndex | None = None


def warm_index(builder: Callable[[], BitIndex]) -> BitIndex:
    """Build the process-wide singleton once; repeated calls return it."""
    global _index
    if _index is not None:
        return _index
    with _lock:
        if _index is None:
            _index = builder()
        return _index


def get_index() -> BitIndex:
    """Return the warm singleton, or raise if nothing has built it yet.

    Deliberately does not build on demand: the caller decides what a cold
    process means. ``api.views.compare`` catches the ``RuntimeError`` and
    warms lazily; anything else would rather fail loudly than silently pay
    for an index build.
    """
    if _index is None:
        raise RuntimeError("BitIndex not warmed yet")
    return _index
