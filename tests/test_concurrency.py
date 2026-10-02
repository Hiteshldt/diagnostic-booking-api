"""
Real race conditions, with real threads. These need row locks, so they only
run on PostgreSQL (SQLite has no SELECT ... FOR UPDATE).
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.payments.models import Payment, WebhookEvent

from .conftest import client_for, future, send_webhook

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs PostgreSQL row locks"),
]

THREADS = 8


def run_together(action):
    """Run `action` in THREADS threads that all start at the same instant."""
    barrier = threading.Barrier(THREADS)

    def worker(_):
        try:
            barrier.wait()
            return action()
        finally:
            connection.close()  # each thread opened its own DB connection

    with ThreadPoolExecutor(THREADS) as pool:
        return list(pool.map(worker, range(THREADS)))


def test_same_webhook_delivered_concurrently_is_applied_once(pending_payment):
    payload = {"event_id": "evt_race", "payment_id": str(pending_payment.id), "status": "SUCCESS"}

    responses = run_together(lambda: send_webhook(APIClient(), payload))

    assert [r.status_code for r in responses] == [200] * THREADS
    assert WebhookEvent.objects.count() == 1
    assert Payment.objects.count() == 1
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCESS
    assert pending_payment.booking.status == Booking.Status.CONFIRMED


def test_conflicting_webhooks_settle_the_payment_exactly_once(pending_payment):
    counter = iter(range(THREADS))
    lock = threading.Lock()

    def deliver():
        with lock:
            n = next(counter)
        status = "SUCCESS" if n % 2 == 0 else "FAILED"
        return send_webhook(APIClient(), {"event_id": f"evt_{n}", "payment_id": str(pending_payment.id), "status": status})

    responses = run_together(deliver)

    assert [r.status_code for r in responses] == [200] * THREADS
    assert sorted(r.json()["status"] for r in responses) == ["IGNORED"] * (THREADS - 1) + ["PROCESSED"]
    pending_payment.refresh_from_db()
    expected_booking = {"SUCCESS": "CONFIRMED", "FAILED": "FAILED"}[pending_payment.status]
    assert pending_payment.booking.status == expected_booking


def test_concurrent_payments_for_one_booking_create_one_payment(user, booking):
    responses = run_together(
        lambda: client_for(user).post("/payments/", {"booking_id": str(booking.id), "simulate": "success"})
    )

    assert sorted(r.status_code for r in responses) == [201] + [409] * (THREADS - 1)
    assert Payment.objects.count() == 1


def test_concurrent_identical_bookings_create_one_booking(user, offering):
    payload = {"centre_id": offering.centre_id, "test_id": offering.test_id, "appointment_at": future().isoformat()}

    responses = run_together(lambda: client_for(user).post("/bookings/", payload))

    assert sorted(r.status_code for r in responses) == [201] + [409] * (THREADS - 1)
    assert Booking.objects.count() == 1
