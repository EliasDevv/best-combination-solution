import pytest

from catalog.normalize import find_suspicious_collisions, normalize_team_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bayern München", "bayern munchen"),
        ("FC Bayern München", "bayern munchen"),
        ("bayern munchen", "bayern munchen"),
        ("Los Angeles FC", "los angeles"),
        ("Real Madrid CF", "real madrid"),
        ("1. FC Köln", "1 koln"),
        ("Borussia   Mönchengladbach", "borussia monchengladbach"),
        ("  RB Leipzig  ", "rb leipzig"),
        ("AS Rom", "as rom"),
        ("Oxford United", "oxford united"),
        ("Beşiktaş", "besiktas"),
    ],
)
def test_normalize_team_name(raw: str, expected: str) -> None:
    assert normalize_team_name(raw) == expected


def test_variants_map_to_same_key() -> None:
    assert normalize_team_name("FC Bayern München") == normalize_team_name("Bayern Munchen")
    assert normalize_team_name("Real Madrid CF") == normalize_team_name("real  madrid")


def test_noise_only_name_does_not_collapse_to_empty() -> None:
    # A club literally named "FC" must keep its name.
    assert normalize_team_name("FC") == "fc"


def test_idempotent() -> None:
    once = normalize_team_name("1. FC Köln")
    assert normalize_team_name(once) == once


class TestFindSuspiciousCollisions:
    def test_differing_noise_tokens_are_flagged(self) -> None:
        # Same key "werder", but SV vs VfL could be two distinct clubs.
        result = find_suspicious_collisions(["SV Werder", "VfL Werder"])
        assert result == {"werder": ["SV Werder", "VfL Werder"]}

    def test_noise_vs_no_noise_is_flagged(self) -> None:
        # Benign in practice, but only a human can tell — report it.
        result = find_suspicious_collisions(["FC Bayern München", "Bayern München"])
        assert list(result) == ["bayern munchen"]

    def test_pure_spelling_variants_are_not_flagged(self) -> None:
        # Case/diacritics/punctuation variants share a noise signature.
        assert find_suspicious_collisions(["Bayern München", "bayern munchen"]) == {}
        assert find_suspicious_collisions(["SV Werder", "sv werder"]) == {}

    def test_distinct_keys_and_singletons_are_not_flagged(self) -> None:
        assert find_suspicious_collisions(["Real Madrid", "RB Leipzig", "FC Bayern"]) == {}
