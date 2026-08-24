"""Write-side helpers — views must not contain ORM logic."""

import uuid
from typing import Any

from .models import SavedSearch


def record_search(params: dict[str, Any], result_summary: dict[str, Any]) -> None:
    """Persist a compare request once per distinct normalized params.

    ``params`` is the normalized request (see api.views.normalize_compare_params),
    so two equivalent requests dedup to one row.
    """
    SavedSearch.objects.get_or_create(params=params, defaults={"result_summary": result_summary})


def delete_search(search_id: uuid.UUID) -> bool:
    """Remove one saved search. Returns False if it was already gone."""
    deleted, _ = SavedSearch.objects.filter(pk=search_id).delete()
    return deleted > 0


def clear_searches() -> int:
    """Drop the whole search history. Returns how many rows went."""
    deleted, _ = SavedSearch.objects.all().delete()
    return deleted
