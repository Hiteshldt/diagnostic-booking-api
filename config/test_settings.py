"""Settings used by pytest: same app, but fast and with no external services."""

from .settings import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
WEBHOOK_SECRET = "test-webhook-secret"

# A rate of None switches a throttle off; test_throttling turns one back on.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = dict.fromkeys(  # noqa: F405
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]  # noqa: F405
)
REST_FRAMEWORK["TEST_REQUEST_DEFAULT_FORMAT"] = "json"  # noqa: F405
