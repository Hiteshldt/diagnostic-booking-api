"""Cross-cutting behaviour: health, error format, docs, rate limiting, request ids."""

import pytest
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db


def test_health(api):
    response = api.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_json_404(api):
    response = api.get("/nope/")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not found."}}


def test_openapi_schema_and_docs_are_served(api):
    schema = api.get("/schema/?format=json")

    assert schema.status_code == 200
    assert "/payments/webhook/" in schema.json()["paths"]
    assert api.get("/docs/").status_code == 200


def test_every_response_carries_a_request_id(api):
    assert api.get("/health/")["X-Request-ID"]
    assert api.get("/health/", HTTP_X_REQUEST_ID="abc-123")["X-Request-ID"] == "abc-123"


def test_login_is_rate_limited(api, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth", "3/min")
    attempt = {"email": "nobody@example.com", "password": "wrong-password"}

    statuses = [api.post("/auth/login/", attempt).status_code for _ in range(4)]

    assert statuses == [401, 401, 401, 429]


def test_api_keeps_working_when_the_cache_is_down(api, user, monkeypatch):
    """Redis going away must not take the API with it: caching and rate limiting both give way."""

    def unavailable(*args, **kwargs):
        raise ConnectionError("redis is down")

    for method in ("get", "set", "incr", "get_or_set"):
        monkeypatch.setattr(f"django.core.cache.backends.locmem.LocMemCache.{method}", unavailable)
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "5/min")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth", "5/min")

    assert api.get("/centres/").status_code == 200
    assert api.post("/auth/login/", {"email": user.email, "password": "Str0ng-pass-123"}).status_code == 200
