"""Database models mirroring the challenge CSV files, plus saved searches.

These models are the *cold-start* representation only: they are read once at
process start to build the in-memory ``BitIndex`` (see ``solver.index``).
The hot request path never touches the database.
"""

import uuid

from django.db import models


class Game(models.Model):
    """A single football match from ``games.csv``.

    The primary key comes from the CSV, so imports are stable across runs.
    """

    id = models.IntegerField(primary_key=True)
    team_home = models.CharField(max_length=255, db_index=True)
    team_away = models.CharField(max_length=255, db_index=True)
    starts_at = models.DateTimeField(db_index=True)
    tournament_name = models.CharField(max_length=255, db_index=True)

    class Meta:
        ordering = ["starts_at", "id"]

    def __str__(self) -> str:
        return f"{self.team_home} vs {self.team_away} ({self.starts_at:%Y-%m-%d})"


class StreamingPackage(models.Model):
    """A bookable streaming subscription from ``streaming_packages.csv``.

    Both price fields are nullable — the source data contains packages with no
    monthly option (yearly-only) and packages with no price at all (e.g. free
    offerings). ``None`` means "not bookable at this billing interval", NOT
    "free"; a free package has an explicit price of ``0``. Pricing logic must
    handle ``None`` explicitly (see ``solver.pricing``).
    """

    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    monthly_price_cents = models.IntegerField(null=True, blank=True)
    monthly_price_yearly_subscription_in_cents = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class StreamingOffer(models.Model):
    """Availability of one game on one package, from ``streaming_offers.csv``."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="offers")
    streaming_package = models.ForeignKey(
        StreamingPackage, on_delete=models.CASCADE, related_name="offers"
    )
    live = models.BooleanField()
    highlights = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["game", "streaming_package"],
                name="unique_offer_per_game_and_package",
            )
        ]

    def __str__(self) -> str:
        return f"game={self.game_id} package={self.streaming_package_id}"


class SavedSearch(models.Model):
    """A stored comparison query and its result summary (bonus feature).

    ``params`` holds the normalized request body of ``POST /api/compare``;
    ``result_summary`` a compact excerpt of the response (best combination,
    coverage, price) so the list view needs no re-computation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    params = models.JSONField()
    result_summary = models.JSONField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"SavedSearch {self.id}"
