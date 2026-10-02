"""
Payment business rules.

Locking: every function that changes a booking or its payment first locks the
booking row (SELECT ... FOR UPDATE), then the payment row. Taking locks in the
same order everywhere means concurrent requests queue up instead of
deadlocking, and each one sees the result of the one before it.
"""

import logging
import random

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.bookings.models import Booking
from apps.core.exceptions import Conflict

from .models import Payment, WebhookEvent

logger = logging.getLogger(__name__)

ACTIVE_PAYMENT_MESSAGE = "A payment already exists for this booking."


def initiate_payment(*, user, booking_id, simulate=None):
    """
    Create a payment for a PENDING booking and simulate the provider's answer.

    simulate: "success" | "failed" | "pending" | None (None = pick at random).
    "pending" leaves the payment unsettled, to be finished by the webhook.
    """
    try:
        with transaction.atomic():
            booking = Booking.objects.select_for_update().filter(pk=booking_id, user=user).first()
            if booking is None:
                raise NotFound("Booking not found.")
            if booking.status != Booking.Status.PENDING:
                raise Conflict(f"Booking is {booking.status} and cannot be paid for.")
            if booking.payments.filter(status__in=[Payment.Status.PENDING, Payment.Status.SUCCESS]).exists():
                raise Conflict(ACTIVE_PAYMENT_MESSAGE)

            payment = Payment.objects.create(booking=booking, amount=booking.amount)

            outcome = simulate or _random_outcome()
            if outcome == "success":
                _settle(payment, booking, Payment.Status.SUCCESS)
            elif outcome == "failed":
                _settle(payment, booking, Payment.Status.FAILED, "Simulated payment failure.")
    except IntegrityError:
        # Backstop for databases without row locks (SQLite): the unique
        # constraint on Payment rejects a second active payment.
        raise Conflict(ACTIVE_PAYMENT_MESSAGE)

    logger.info(
        "payment initiated",
        extra={"ctx": {"payment_id": payment.id, "booking_id": booking.id, "status": payment.status}},
    )
    return payment


def _random_outcome():
    return "success" if random.random() < settings.PAYMENT_SUCCESS_RATE else "failed"


def _settle(payment, booking, status, failure_reason=""):
    """Record the payment's final result and move the booking along with it."""
    payment.status = status
    payment.failure_reason = failure_reason
    payment.save(update_fields=["status", "failure_reason", "updated_at"])

    if booking.status == Booking.Status.PENDING:
        paid = status == Payment.Status.SUCCESS
        booking.transition_to(Booking.Status.CONFIRMED if paid else Booking.Status.FAILED)
    else:
        # e.g. the user cancelled while the payment was in flight. The booking
        # stays as it is; a successful payment here would need a refund.
        logger.warning(
            "payment settled for a booking that is no longer pending",
            extra={"ctx": {"payment_id": payment.id, "booking_status": booking.status, "payment_status": status}},
        )


def receive_event(*, event_id, payload):
    """
    Store the event. Returns (event, created).

    get_or_create leans on the unique constraint on event_id, so two identical
    deliveries arriving together still end up with exactly one row.
    """
    return WebhookEvent.objects.get_or_create(event_id=event_id, defaults={"payload": payload})


def process_event(event_pk):
    """
    Apply a stored webhook event to its payment. Safe to call any number of
    times: once the event is PROCESSED or IGNORED, later calls change nothing.
    """
    with transaction.atomic():
        event = WebhookEvent.objects.select_for_update().get(pk=event_pk)
        if event.is_final:
            return event

        payment = Payment.objects.filter(pk=event.payload["payment_id"]).first()
        if payment is None:
            return _finish(event, WebhookEvent.Status.FAILED, "Unknown payment.")

        booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        event.payment = payment
        new_status = event.payload["status"]

        if payment.status == Payment.Status.PENDING:
            _settle(payment, booking, new_status, event.payload.get("failure_reason", ""))
            return _finish(event, WebhookEvent.Status.PROCESSED)

        # The payment already has a final result. Never overwrite it: a late or
        # contradictory event must not flip SUCCESS to FAILED or back.
        return _finish(
            event, WebhookEvent.Status.IGNORED, f"Payment was already {payment.status}; {new_status} not applied."
        )


def _finish(event, status, note=""):
    event.status = status
    event.note = note
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "note", "processed_at", "payment"])
    logger.info(
        "webhook event handled",
        extra={"ctx": {"event_id": event.event_id, "status": status, "note": note}},
    )
    return event
