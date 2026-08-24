"""Development settings: permissive defaults, local-memory cache."""

from .base import *  # noqa: F403

DEBUG = True

# Development-only fallback so the project runs without any configuration.
# Production refuses to start without a real DJANGO_SECRET_KEY (see prod.py).
SECRET_KEY = SECRET_KEY or "dev-only-insecure-secret-key"

ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "best-combination",
    }
}
