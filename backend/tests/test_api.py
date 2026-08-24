"""API contract tests, running the real solver against the sample dataset."""

from datetime import UTC, datetime

import pytest
from rest_framework.test import APIClient

from api.views import compare_cache_key, normalize_compare_params
from catalog import selectors
from catalog.models import Game, SavedSearch


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def st_roster(db) -> None:
    """Teams chosen so the query "st" hits every ranking tier: whole-name
    prefix (Stuttgarter Kickers), word prefix (VfB Stuttgart, FC St. Pauli —
    the dot must count as a word boundary), and mere substring (Ajax
    Amsterdam, Aston Villa)."""
    Game.objects.bulk_create(
        [
            Game(
                id=101,
                team_home="VfB Stuttgart",
                team_away="Ajax Amsterdam",
                starts_at=datetime(2024, 8, 24, 16, 30, tzinfo=UTC),
                tournament_name="Testliga",
            ),
            Game(
                id=102,
                team_home="FC St. Pauli",
                team_away="Aston Villa",
                starts_at=datetime(2024, 8, 25, 16, 30, tzinfo=UTC),
                tournament_name="Testliga",
            ),
            Game(
                id=103,
                team_home="Stuttgarter Kickers",
                team_away="Bayern München",
                starts_at=datetime(2024, 8, 26, 16, 30, tzinfo=UTC),
                tournament_name="Testliga",
            ),
        ]
    )


class TestTeamsEndpoint:
    def test_returns_matching_names(self, client: APIClient, sample_dataset: dict) -> None:
        response = client.get("/api/teams", {"q": "leip"})
        assert response.status_code == 200
        assert response.json() == {"teams": ["RB Leipzig"]}

    def test_empty_query_returns_empty_list(self, client: APIClient, db) -> None:
        response = client.get("/api/teams")
        assert response.status_code == 200
        assert response.json() == {"teams": []}

    def test_word_prefix_ranks_before_substring(self, client: APIClient, st_roster) -> None:
        teams = client.get("/api/teams", {"q": "st"}).json()["teams"]
        for word_prefix in ("VfB Stuttgart", "FC St. Pauli"):
            for substring_only in ("Ajax Amsterdam", "Aston Villa"):
                assert teams.index(word_prefix) < teams.index(substring_only)

    def test_name_prefix_ranks_before_word_prefix(self, client: APIClient, st_roster) -> None:
        teams = client.get("/api/teams", {"q": "st"}).json()["teams"]
        assert teams[0] == "Stuttgarter Kickers"
        assert "VfB Stuttgart" in teams and "FC St. Pauli" in teams

    def test_alphabetical_within_each_tier(self, client: APIClient, st_roster) -> None:
        teams = client.get("/api/teams", {"q": "st"}).json()["teams"]
        assert teams == [
            "Stuttgarter Kickers",  # tier 1: whole-name prefix
            "FC St. Pauli",  # tier 2, alphabetical
            "VfB Stuttgart",
            "Ajax Amsterdam",  # tier 3, alphabetical
            "Aston Villa",
        ]

    def test_matches_diacritics_insensitively(self, client: APIClient, st_roster) -> None:
        response = client.get("/api/teams", {"q": "munchen"})
        assert response.json() == {"teams": ["Bayern München"]}

    def test_limit_fills_tiers_in_order(self, st_roster) -> None:
        assert selectors.search_team_names("st", limit=3) == [
            "Stuttgarter Kickers",
            "FC St. Pauli",
            "VfB Stuttgart",
        ]


class TestTournamentsEndpoint:
    def test_lists_distinct_tournaments(self, client: APIClient, sample_dataset: dict) -> None:
        response = client.get("/api/tournaments")
        assert response.status_code == 200
        assert response.json() == {"tournaments": ["Bundesliga", "UEFA Champions League"]}


class TestCompareEndpoint:
    def test_solves_rb_leipzig_query_exactly(self, client: APIClient, warmed_index) -> None:
        """End-to-end against the sample dataset with hand-computed numbers.

        Sky (id 7) streams the two August games live: 1 chained month at
        4499. DAZN (id 12) streams the September CL game but is yearly-only:
        12 x 2499 = 29988. Full coverage needs both: 34487.
        """
        response = client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"games", "packages", "best_combination", "pareto", "unknown_teams"}
        assert body["unknown_teams"] == []

        assert [g["id"] for g in body["games"]] == [1, 2, 3]
        assert body["games"][0]["home"] == "Bayern München"
        assert body["games"][2]["tournament"] == "UEFA Champions League"

        by_id = {p["id"]: p for p in body["packages"]}
        assert by_id[7]["live_idx"] == [0, 1]
        assert by_id[7]["highlight_idx"] == [0, 1]
        assert by_id[7]["cost_cents"] == 4499
        assert by_id[12]["live_idx"] == [2]
        assert by_id[12]["highlight_idx"] == []
        assert by_id[12]["cost_cents"] == 12 * 2499

        assert body["best_combination"] == {
            "package_ids": [7, 12],
            "cost_cents": 4499 + 12 * 2499,
            "coverage": 1.0,
            "exact": True,
        }
        assert body["pareto"][0]["coverage"] == 1.0
        assert body["pareto"][0]["cost_cents"] == 4499 + 12 * 2499
        assert body["pareto"][1]["package_ids"] == [7]
        assert body["pareto"][1]["cost_cents"] == 4499

    def test_unknown_teams_are_reported_not_swallowed(
        self, client: APIClient, warmed_index
    ) -> None:
        """A typo must not silently resolve to 'no games' — the response
        names the teams that matched nothing."""
        response = client.post(
            "/api/compare", {"teams": ["RB Leipzig", "RB Leipzgi"]}, format="json"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["unknown_teams"] == ["RB Leipzgi"]
        # The known team still gets its games.
        assert len(body["games"]) == 3

    def test_empty_teams_means_all_games(self, client: APIClient, warmed_index) -> None:
        response = client.post("/api/compare", {"teams": []}, format="json")
        assert response.status_code == 200
        assert len(response.json()["games"]) == 3

    def test_cold_index_warms_on_first_request(
        self, client: APIClient, sample_dataset: dict, monkeypatch
    ) -> None:
        """The BitIndex builds lazily inside the first compare request (there
        is no eager warm-up in AppConfig.ready() by design)."""
        monkeypatch.setattr("solver.index._index", None)
        response = client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")
        assert response.status_code == 200
        assert len(response.json()["games"]) == 3

    def test_rejects_missing_teams(self, client: APIClient, db) -> None:
        response = client.post("/api/compare", {}, format="json")
        assert response.status_code == 400

    def test_rejects_unknown_requirement(self, client: APIClient, db) -> None:
        response = client.post(
            "/api/compare", {"teams": ["X"], "requirement": "replay"}, format="json"
        )
        assert response.status_code == 400

    def test_rejects_inverted_date_range(self, client: APIClient, warmed_index) -> None:
        """A backwards range must 400, not silently return the games outside it.

        The date mask is two bisected offsets XORed together, so from > to
        selects the complement of the intended window — the one wrong answer
        that looks like a valid one.
        """
        response = client.post(
            "/api/compare",
            {"teams": ["RB Leipzig"], "date_from": "2024-09-30", "date_to": "2024-08-01"},
            format="json",
        )
        assert response.status_code == 400
        assert "date_to" in response.json()

    def test_accepts_a_single_day_range(self, client: APIClient, warmed_index) -> None:
        """The boundary the rejection must not swallow: from == to is one day."""
        response = client.post(
            "/api/compare",
            {"teams": ["RB Leipzig"], "date_from": "2024-08-24", "date_to": "2024-08-24"},
            format="json",
        )
        assert response.status_code == 200
        assert [game["id"] for game in response.json()["games"]] == [1]

    def test_saves_search_once_per_distinct_params(self, client: APIClient, warmed_index) -> None:
        client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")
        # Same normalized request again (cache hit) and in different order.
        client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")
        assert SavedSearch.objects.count() == 1
        saved = SavedSearch.objects.get()
        assert saved.params["teams"] == ["RB Leipzig"]
        assert saved.result_summary["coverage"] == 1.0

    def test_cache_hit_still_records_the_search(self, client: APIClient, warmed_index) -> None:
        """Clearing the history must not hide later searches: a repeat request
        answered from the compare cache is still recorded."""
        client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")
        SavedSearch.objects.all().delete()

        # Same normalized request -> served from cache, but recorded again.
        client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")

        assert SavedSearch.objects.count() == 1

    def test_record_search_failure_does_not_break_response(
        self, client: APIClient, warmed_index, monkeypatch
    ) -> None:
        """The saved-search write is bonus bookkeeping — a DB failure there
        must not turn a fully computed comparison into an error response."""

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("database gone")

        monkeypatch.setattr("api.views.services.record_search", boom)
        response = client.post("/api/compare", {"teams": ["RB Leipzig"]}, format="json")
        assert response.status_code == 200
        assert response.json()["best_combination"]["package_ids"] == [7, 12]


class TestSearchesEndpoint:
    def test_empty_list_without_saved_searches(self, client: APIClient, db) -> None:
        response = client.get("/api/searches")
        assert response.status_code == 200
        assert response.json() == {"searches": []}

    def test_delete_removes_only_the_targeted_search(self, client: APIClient, db) -> None:
        keep = SavedSearch.objects.create(params={"teams": ["A"]}, result_summary={})
        drop = SavedSearch.objects.create(params={"teams": ["B"]}, result_summary={})

        response = client.delete(f"/api/searches/{drop.id}")

        assert response.status_code == 204
        assert list(SavedSearch.objects.values_list("id", flat=True)) == [keep.id]

    def test_delete_is_idempotent(self, client: APIClient, db) -> None:
        search = SavedSearch.objects.create(params={"teams": ["A"]}, result_summary={})
        assert client.delete(f"/api/searches/{search.id}").status_code == 204
        assert client.delete(f"/api/searches/{search.id}").status_code == 204

    def test_delete_collection_clears_the_history(self, client: APIClient, db) -> None:
        SavedSearch.objects.create(params={"teams": ["A"]}, result_summary={})
        SavedSearch.objects.create(params={"teams": ["B"]}, result_summary={})

        response = client.delete("/api/searches")

        assert response.status_code == 204
        assert SavedSearch.objects.count() == 0
        # Idempotent: clearing an already empty history is still a 204.
        assert client.delete("/api/searches").status_code == 204


class TestCacheKey:
    def test_team_order_does_not_change_key(self) -> None:
        a = normalize_compare_params({"teams": ["B", "A"]})
        b = normalize_compare_params({"teams": ["A", "B", "A"]})
        assert compare_cache_key(a) == compare_cache_key(b)

    def test_explicit_defaults_equal_omitted_defaults(self) -> None:
        a = normalize_compare_params({"teams": ["A"]})
        b = normalize_compare_params({"teams": ["A"], "requirement": "live"})
        assert compare_cache_key(a) == compare_cache_key(b)

    def test_different_params_change_key(self) -> None:
        a = normalize_compare_params({"teams": ["A"]})
        b = normalize_compare_params({"teams": ["A"], "requirement": "both"})
        assert compare_cache_key(a) != compare_cache_key(b)
