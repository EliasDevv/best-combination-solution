"""Tests for solver.index — BitIndex construction and the warm-up singleton."""

import threading
import time
from datetime import UTC, datetime

import pytest

from solver.index import BitIndex, build_index, get_index, warm_index

GAMES = [
    {
        "id": 3,
        "team_home": "real madrid",
        "team_away": "rb leipzig",
        "team_home_display": "Real Madrid",
        "team_away_display": "RB Leipzig",
        "starts_at": datetime(2024, 9, 17, 19, 0, tzinfo=UTC),
        "tournament_name": "UEFA Champions League",
    },
    {
        "id": 1,
        "team_home": "bayern munchen",
        "team_away": "rb leipzig",
        "team_home_display": "Bayern München",
        "team_away_display": "RB Leipzig",
        "starts_at": datetime(2024, 8, 24, 16, 30, tzinfo=UTC),
        "tournament_name": "Bundesliga",
    },
    {
        "id": 2,
        "team_home": "rb leipzig",
        "team_away": "borussia dortmund",
        "team_home_display": "RB Leipzig",
        "team_away_display": "Borussia Dortmund",
        "starts_at": datetime(2024, 8, 31, 16, 30, tzinfo=UTC),
        "tournament_name": "Bundesliga",
    },
]

PACKAGES = [
    {"id": 7, "name": "Sky Sport", "monthly_price_cents": 4499, "yearly_monthly_price_cents": 3999},
    {"id": 12, "name": "DAZN", "monthly_price_cents": None, "yearly_monthly_price_cents": 2499},
]

OFFERS = [
    {"game_id": 1, "package_id": 7, "live": True, "highlights": True},
    {"game_id": 2, "package_id": 7, "live": True, "highlights": True},
    {"game_id": 3, "package_id": 12, "live": True, "highlights": False},
]


@pytest.fixture
def index() -> BitIndex:
    return build_index(games=GAMES, packages=PACKAGES, offers=OFFERS)


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch) -> None:
    monkeypatch.setattr("solver.index._index", None)


class TestBuildIndex:
    def test_empty_dataset(self) -> None:
        index = build_index(games=[], packages=[], offers=[])
        assert index.game_ids == ()
        assert index.game_meta == ()
        assert index.game_starts == ()

    def test_bits_ordered_by_starts_at_then_id(self, index: BitIndex) -> None:
        # Input deliberately unsorted; bit order must be chronological.
        assert index.game_ids == (1, 2, 3)
        assert index.game_pos == {1: 0, 2: 1, 3: 2}
        assert index.game_starts == tuple(sorted(index.game_starts))

    def test_team_masks_use_normalized_keys_home_and_away(self, index: BitIndex) -> None:
        assert index.team_mask["rb leipzig"] == 0b111
        assert index.team_mask["bayern munchen"] == 0b001
        assert index.team_mask["borussia dortmund"] == 0b010
        assert "RB Leipzig" not in index.team_mask

    def test_tournament_and_month_masks(self, index: BitIndex) -> None:
        assert index.tournament_mask["Bundesliga"] == 0b011
        assert index.tournament_mask["UEFA Champions League"] == 0b100
        assert index.month_mask["2024-08"] == 0b011
        assert index.month_mask["2024-09"] == 0b100
        assert index.game_month == ("2024-08", "2024-08", "2024-09")

    def test_live_and_highlight_masks(self, index: BitIndex) -> None:
        assert index.live_mask[7] == 0b011
        assert index.highlight_mask[7] == 0b011
        # DAZN offer is live-only.
        assert index.live_mask[12] == 0b100
        assert index.highlight_mask[12] == 0b000

    def test_game_meta_keeps_display_names(self, index: BitIndex) -> None:
        meta = index.game_meta[0]
        assert meta.id == 1
        assert meta.team_home == "Bayern München"
        assert meta.tournament_name == "Bundesliga"

    def test_packages_mapping(self, index: BitIndex) -> None:
        assert index.packages[12].monthly_price_cents is None
        assert index.packages[12].yearly_monthly_price_cents == 2499

    def test_offer_with_unknown_game_raises(self) -> None:
        bad = [{"game_id": 99, "package_id": 7, "live": True, "highlights": False}]
        with pytest.raises(ValueError, match="unknown game id 99"):
            build_index(games=GAMES, packages=PACKAGES, offers=bad)

    def test_offer_with_unknown_package_raises(self) -> None:
        bad = [{"game_id": 1, "package_id": 99, "live": True, "highlights": False}]
        with pytest.raises(ValueError, match="unknown package id 99"):
            build_index(games=GAMES, packages=PACKAGES, offers=bad)

    def test_accepts_iso_strings_for_starts_at(self) -> None:
        games = [{**GAMES[1], "starts_at": "2024-08-24T16:30:00+00:00"}]
        index = build_index(games=games, packages=[], offers=[])
        assert index.game_starts[0] == datetime(2024, 8, 24, 16, 30, tzinfo=UTC)

    def test_masks_are_read_only(self, index: BitIndex) -> None:
        with pytest.raises(TypeError):
            index.team_mask["x"] = 1  # type: ignore[index]


class TestSingleton:
    def test_get_index_raises_before_warmup(self) -> None:
        with pytest.raises(RuntimeError):
            get_index()

    def test_warm_index_builds_once(self) -> None:
        calls = 0

        def builder() -> BitIndex:
            nonlocal calls
            calls += 1
            return build_index(games=[], packages=[], offers=[])

        first = warm_index(builder)
        second = warm_index(builder)
        assert first is second
        assert get_index() is first
        assert calls == 1

    def test_warm_index_is_thread_safe(self) -> None:
        calls = 0

        def slow_builder() -> BitIndex:
            nonlocal calls
            calls += 1
            time.sleep(0.02)
            return build_index(games=[], packages=[], offers=[])

        results: list[BitIndex] = []
        threads = [
            threading.Thread(target=lambda: results.append(warm_index(slow_builder)))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert calls == 1
        assert all(r is results[0] for r in results)
