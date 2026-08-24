"""Request serializers for the comparison API.

The compare *response* is not serialized here — ``api.views._build_payload``
assembles it straight from index data. It references games by *index into the
games array* (not by id) in ``live_idx``/``highlight_idx`` to keep the payload
small: the matrix of ~40 packages x thousands of games would otherwise repeat
game ids everywhere.
"""

from typing import Any

from rest_framework import serializers

REQUIREMENT_CHOICES = ("live", "highlights", "both")
OBJECTIVE_CHOICES = ("min_price", "min_packages")
BILLING_CHOICES = ("monthly_chained", "yearly", "flexible")

# Defaults applied during request normalization; also part of the cache key
# computation (see api.views.compare_cache_key).
COMPARE_DEFAULTS: dict[str, Any] = {
    "tournaments": [],
    "date_from": None,
    "date_to": None,
    "requirement": "live",
    "objective": "min_price",
    "billing": "monthly_chained",
}


class CompareRequestSerializer(serializers.Serializer):
    """Body of POST /api/compare."""

    # An explicit empty list means "all games" (reference query 3: fewest
    # services covering everything); a missing field is still a 400.
    teams = serializers.ListField(child=serializers.CharField(max_length=255), allow_empty=True)
    tournaments = serializers.ListField(
        child=serializers.CharField(max_length=255), required=False, default=list
    )
    date_from = serializers.DateField(required=False, allow_null=True, default=None)
    date_to = serializers.DateField(required=False, allow_null=True, default=None)
    requirement = serializers.ChoiceField(choices=REQUIREMENT_CHOICES, default="live")
    objective = serializers.ChoiceField(choices=OBJECTIVE_CHOICES, default="min_price")
    billing = serializers.ChoiceField(choices=BILLING_CHOICES, default="monthly_chained")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject an inverted date range instead of solving something else.

        The index stores games in (starts_at, id) order and derives a range
        from two bisected offsets, so ``date_from > date_to`` would not yield
        an empty range but the games *outside* the requested window — a wrong
        answer dressed up as a valid one. There is no sensible reading of a
        backwards range, so it is a 400.
        """
        date_from, date_to = attrs.get("date_from"), attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_to": "The end of the date range must not be before its start."}
            )
        return attrs


class SavedSearchSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    created_at = serializers.DateTimeField()
    params = serializers.JSONField()
    result_summary = serializers.JSONField()
