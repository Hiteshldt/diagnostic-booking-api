"""
Django settings.

Everything environment-specific comes from environment variables, and every
variable has a default that works on a laptop with nothing else installed:
SQLite instead of Postgres, an in-process cache instead of Redis, and Celery
tasks running inline instead of on a worker.
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


SECRET_KEY = os.environ.get(
    "SECRET_KEY", "dev-only-secret-key-change-me-before-deploying-anywhere"
)
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts",
    "apps.centres",
    "apps.bookings",
    "apps.payments",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,  # drf-spectacular's Swagger UI page
    }
]

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# --- Time -------------------------------------------------------------------

USE_TZ = True
TIME_ZONE = "UTC"

# --- Cache (Redis when available) -------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL")

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CENTRE_CACHE_TTL = int(os.environ.get("CENTRE_CACHE_TTL", 300))

# --- API --------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttling.AnonRateThrottle",
        "apps.core.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "120/min",
        "auth": "10/min",  # signup + login: slows down password guessing
        "payments": "20/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "EVE Healthcare - Diagnostic Bookings API",
    "DESCRIPTION": "Diagnostic test bookings with simulated payments.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Payments ---------------------------------------------------------------

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "dev-webhook-secret")
PAYMENT_SUCCESS_RATE = float(os.environ.get("PAYMENT_SUCCESS_RATE", 0.8))
# A PENDING booking nobody pays for is cancelled after this long.
BOOKING_PAYMENT_WINDOW_MINUTES = int(os.environ.get("BOOKING_PAYMENT_WINDOW_MINUTES", 30))

# --- Celery -----------------------------------------------------------------

if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
else:
    # No broker: run tasks inline so the app still works end to end.
    CELERY_TASK_ALWAYS_EAGER = True

CELERY_TASK_IGNORE_RESULT = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False  # keep our JSON log format in the worker
CELERY_BEAT_SCHEDULE = {
    "expire-unpaid-bookings": {
        "task": "apps.bookings.tasks.expire_unpaid_bookings",
        "schedule": 300,
    },
    "retry-stuck-webhook-events": {
        "task": "apps.payments.tasks.retry_stuck_webhook_events",
        "schedule": 60,
    },
}

# --- Logging: one JSON object per line --------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
