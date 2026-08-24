from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """The BitIndex is deliberately NOT warmed here: ready() runs for every
    management command (migrate would query a schema that may not exist yet)
    and Django warns loudly about DB access during app initialization. The
    index is built lazily on the first compare request instead — see
    ``api.views.compare`` and the lock in ``solver.index.warm_index``.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"
