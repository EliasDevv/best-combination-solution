"""Shared fixtures: a tiny but realistic dataset for API and import tests."""

from datetime import UTC, datetime

import pytest
from django.core.cache import cache

from catalog.models import Game, StreamingOffer, StreamingPackage


@pytest.fixture(autouse=True)
def clear_compare_cache():
    """LocMemCache persists within the test process — isolate every test."""
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def reset_bit_index(monkeypatch):
    """The index warms lazily on first request — an index built from one
    test's database must never leak into the next test."""
    monkeypatch.setattr("solver.index._index", None)
    yield


@pytest.fixture
def warmed_index(sample_dataset: dict, monkeypatch):
    """Build the BitIndex from the sample dataset and install it as the
    process singleton for the duration of the test.
    """
    from catalog.selectors import build_index_from_db

    index = build_index_from_db()
    monkeypatch.setattr("solver.index._index", index)
    return index


@pytest.fixture
def sample_dataset(db) -> dict:
    """Three games, two packages, partial coverage — enough for every endpoint."""
    games = Game.objects.bulk_create(
        [
            Game(
                id=1,
                team_home="Bayern München",
                team_away="RB Leipzig",
                starts_at=datetime(2024, 8, 24, 16, 30, tzinfo=UTC),
                tournament_name="Bundesliga",
            ),
            Game(
                id=2,
                team_home="RB Leipzig",
                team_away="Borussia Dortmund",
                starts_at=datetime(2024, 8, 31, 16, 30, tzinfo=UTC),
                tournament_name="Bundesliga",
            ),
            Game(
                id=3,
                team_home="Real Madrid",
                team_away="RB Leipzig",
                starts_at=datetime(2024, 9, 17, 19, 0, tzinfo=UTC),
                tournament_name="UEFA Champions League",
            ),
        ]
    )
    packages = StreamingPackage.objects.bulk_create(
        [
            StreamingPackage(
                id=7,
                name="Sky Sport",
                monthly_price_cents=4499,
                monthly_price_yearly_subscription_in_cents=3999,
            ),
            StreamingPackage(
                id=12,
                name="DAZN",
                monthly_price_cents=None,  # yearly-only package
                monthly_price_yearly_subscription_in_cents=2499,
            ),
        ]
    )
    offers = StreamingOffer.objects.bulk_create(
        [
            StreamingOffer(game_id=1, streaming_package_id=7, live=True, highlights=True),
            StreamingOffer(game_id=2, streaming_package_id=7, live=True, highlights=True),
            StreamingOffer(game_id=3, streaming_package_id=12, live=True, highlights=False),
        ]
    )
    return {"games": games, "packages": packages, "offers": offers}
