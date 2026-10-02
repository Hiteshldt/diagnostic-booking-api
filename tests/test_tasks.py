from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.tasks import expire_unpaid_bookings
from apps.payments.models import Payment, WebhookEvent
from apps.payments.tasks import process_webhook_event, retry_stuck_webhook_events

from .conftest import future

pytestmark = pytest.mark.django_db


def make_booking(user, offering, *, age_minutes, status=Booking.Status.PENDING, days=3):
    booking = Booking.objects.create(
        user=user, centre_test=offering, appointment_at=future(days), amount=offering.price, status=status
    )
    Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now() - timedelta(minutes=age_minutes))
    return booking


def test_expire_unpaid_bookings_only_cancels_stale_unpaid_ones(user, offering):
    stale = make_booking(user, offering, age_minutes=45, days=1)
    fresh = make_booking(user, offering, age_minutes=5, days=2)
    awaiting_webhook = make_booking(user, offering, age_minutes=45, days=3)
    Payment.objects.create(booking=awaiting_webhook, amount=offering.price)
    confirmed = make_booking(user, offering, age_minutes=45, days=4, status=Booking.Status.CONFIRMED)

    assert expire_unpaid_bookings() == 1

    statuses = {b.pk: b.status for b in Booking.objects.all()}
    assert statuses == {
        stale.pk: "CANCELLED",
        fresh.pk: "PENDING",
        awaiting_webhook.pk: "PENDING",
        confirmed.pk: "CONFIRMED",
    }


def test_stuck_webhook_events_are_picked_up_and_applied(pending_payment):
    payload = {"event_id": "evt_stuck", "payment_id": str(pending_payment.id), "status": "SUCCESS"}
    stuck = WebhookEvent.objects.create(event_id="evt_stuck", payload=payload)
    WebhookEvent.objects.filter(pk=stuck.pk).update(received_at=timezone.now() - timedelta(minutes=5))
    WebhookEvent.objects.create(event_id="evt_just_arrived", payload={**payload, "event_id": "evt_just_arrived"})

    assert retry_stuck_webhook_events() == 1  # tasks run inline in tests

    stuck.refresh_from_db()
    pending_payment.refresh_from_db()
    assert stuck.status == WebhookEvent.Status.PROCESSED
    assert pending_payment.status == Payment.Status.SUCCESS
    assert WebhookEvent.objects.get(event_id="evt_just_arrived").status == WebhookEvent.Status.RECEIVED


def test_webhook_task_is_configured_to_retry_with_backoff():
    assert process_webhook_event.max_retries == 5
    assert process_webhook_event.retry_backoff is True
