"""
Caching for the centre catalogue (read often, changed rarely).

Instead of hunting down and deleting every cached page when something changes,
all keys carry a version number. Any write bumps the version, so every old key
simply stops being read and expires on its own.

The cache is an optimisation, never a dependency: if Redis is down we log it
and fall back to the database.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save

from .models import CentreTest, DiagnosticCentre, DiagnosticTest

logger = logging.getLogger(__name__)

VERSION_KEY = "centres:version"


def _key(url):
    version = cache.get_or_set(VERSION_KEY, 1, None)
    return f"centres:v{version}:{hashlib.md5(url.encode()).hexdigest()}"


def get_cached(url):
    try:
        return cache.get(_key(url))
    except Exception:
        logger.warning("cache read failed", exc_info=True)
        return None


def set_cached(url, data):
    try:
        cache.set(_key(url), data, settings.CENTRE_CACHE_TTL)
    except Exception:
        logger.warning("cache write failed", exc_info=True)


def invalidate():
    try:
        cache.incr(VERSION_KEY)
    except ValueError:  # key not set yet
        cache.set(VERSION_KEY, 1, None)
    except Exception:
        logger.warning("cache invalidation failed", exc_info=True)


def _on_change(**kwargs):
    # Wait for the commit, otherwise a reader could re-cache the old rows.
    transaction.on_commit(invalidate)


for _model in (DiagnosticCentre, DiagnosticTest, CentreTest):
    post_save.connect(_on_change, sender=_model, dispatch_uid=f"cache-save-{_model.__name__}")
    post_delete.connect(_on_change, sender=_model, dispatch_uid=f"cache-delete-{_model.__name__}")
