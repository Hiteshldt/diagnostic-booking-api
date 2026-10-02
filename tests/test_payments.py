import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.bookings.models import Booking
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def pay(client, booking_id, simulate=None):
    payload = {"booking_id": str(booking_id)}
    if simulate:
        payload["simulate"] = simulate
    return client.post("/payments/", payload)


def test_successful_payment_confirms_the_booking(user_api, booking):
    response = pay(user_api, booking.id, "success")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["amount"] == "500.00"
    assert body["booking_id"] == str(booking.id)
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CONFIRMED


def test_failed_payment_fails_the_booking(user_api, booking):
    response = pay(user_api, booking.id, "failed")

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert response.json()["failure_reason"]
    booking.refresh_from_db()
    assert booking.status == Booking.Status.FAILED


def test_pending_payment_leaves_the_booking_waiting_for_the_webhook(user_api, booking):
    response = pay(user_api, booking.id, "pending")

    assert response.json()["status"] == "PENDING"
    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING


@pytest.mark.parametrize("roll, expected", [(0.1, "SUCCESS"), (0.95, "FAILED")])
def test_outcome_is_random_when_not_forced(user_api, booking, monkeypatch, roll, expected):
    monkeypatch.setattr("apps.payments.services.random.random", lambda: roll)

    assert pay(user_api, booking.id).json()["status"] == expected


def test_payment_requires_authentication(api, booking):
    assert pay(api, booking.id, "success").status_code == 401
    assert Payment.objects.count() == 0


def test_unknown_booking_is_not_found(user_api):
    response = pay(user_api, uuid.uuid4(), "success")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("payload", [{}, {"booking_id": "not-a-uuid"}, {"booking_id": ""}])
def test_malformed_booking_id_is_a_validation_error(user_api, payload):
    response = user_api.post("/payments/", payload)

    assert response.status_code == 400
    assert "booking_id" in response.json()["error"]["details"]


def test_invalid_simulate_value_is_rejected(user_api, booking):
    assert pay(user_api, booking.id, "maybe").status_code == 400


def test_cannot_pay_for_someone_elses_booking(other_api, booking):
    response = pay(other_api, booking.id, "success")

    assert response.status_code == 404
    assert Payment.objects.count() == 0
    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING


def test_confirmed_booking_cannot_be_paid_twice(user_api, booking):
    pay(user_api, booking.id, "success")

    response = pay(user_api, booking.id, "success")

    assert response.status_code == 409
    assert Payment.objects.count() == 1


def test_second_payment_is_refused_while_one_is_in_flight(user_api, booking):
    pay(user_api, booking.id, "pending")

    response = pay(user_api, booking.id, "success")

    assert response.status_code == 409
    assert Payment.objects.count() == 1


@pytest.mark.parametrize("status", [Booking.Status.CANCELLED, Booking.Status.FAILED])
def test_finished_booking_cannot_be_paid(user_api, booking, status):
    Booking.objects.filter(pk=booking.pk).update(status=status)

    assert pay(user_api, booking.id, "success").status_code == 409
    assert Payment.objects.count() == 0


def test_database_rejects_a_second_active_payment(booking, pending_payment):
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(booking=booking, amount=booking.amount)


def test_users_only_see_their_own_payments(user_api, other_api, booking):
    payment_id = pay(user_api, booking.id, "success").json()["id"]

    assert user_api.get(f"/payments/{payment_id}/").status_code == 200
    assert user_api.get("/payments/").json()["count"] == 1
    assert other_api.get(f"/payments/{payment_id}/").status_code == 404
    assert other_api.get("/payments/").json()["count"] == 0
