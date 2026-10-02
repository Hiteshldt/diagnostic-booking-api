from django.apps import AppConfig


class CentresConfig(AppConfig):
    name = "apps.centres"

    def ready(self):
        from . import cache  # noqa: F401  (connects the cache-invalidation signals)
