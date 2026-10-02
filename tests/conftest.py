import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.centres.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.payments import signature
from apps.payments.models import Payment

User = get_user_model()
PASSWORD = "Str0ng-pass-123"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


@pytest.fixture
def api():
    """An anonymous client."""
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user("patient@example.com", PASSWORD)


@pytest.fixture
def other_user(db):
    return User.objects.create_user("someone-else@example.com", PASSWORD)


@pytest.fixture
def admin(db):
    return User.objects.create_user("admin@example.com", PASSWORD, is_staff=True)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def user_api(user):
    return client_for(user)


@pytest.fixture
def other_api(other_user):
    return client_for(other_user)


@pytest.fixture
def admin_api(admin):
    return client_for(admin)


@pytest.fixture
def offering(db):
    """A centre offering one test for 500.00."""
    centre = DiagnosticCentre.objects.create(name="EVE Diagnostics", location="Bengaluru")
    test = DiagnosticTest.objects.create(name="Complete Blood Count")
    return CentreTest.objects.create(centre=centre, test=test, price=Decimal("500.00"))


def future(days=3):
    return timezone.now() + timedelta(days=days)


@pytest.fixture
def booking(user, offering):
    return Booking.objects.create(user=user, centre_test=offering, appointment_at=future(), amount=offering.price)


@pytest.fixture
def pending_payment(booking):
    return Payment.objects.create(booking=booking, amount=booking.amount)


def send_webhook(client, payload, signature_value=None):
    """POST a webhook the way the provider would: raw JSON body + HMAC signature."""
    body = json.dumps(payload, default=str)
    if signature_value is None:
        signature_value = signature.sign(body.encode())
    return client.post(
        "/payments/webhook/",
        data=body,
        content_type="application/json",
        HTTP_X_WEBHOOK_SIGNATURE=signature_value,
    )
