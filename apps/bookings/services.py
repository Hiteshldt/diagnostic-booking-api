"""Booking business rules. Views stay thin and call into here."""

import logging

from django.db import IntegrityError, transaction

from apps.core.exceptions import Conflict

from .models import Booking, InvalidTransition

logger = logging.getLogger(__name__)

DUPLICATE_MESSAGE = "You already have an active booking for this test at this time."


def create_booking(*, user, centre_test, appointment_at):
    slot = {"user": user, "centre_test": centre_test, "appointment_at": appointment_at}
    active = [Booking.Status.PENDING, Booking.Status.CONFIRMED]
    if Booking.objects.filter(**slot, status__in=active).exists():
        raise Conflict(DUPLICATE_MESSAGE)
    try:
        with transaction.atomic():
            booking = Booking.objects.create(**slot, amount=centre_test.price)
    except IntegrityError:
        # Two identical requests raced past the check above; the unique
        # constraint stopped the second one.
        raise Conflict(DUPLICATE_MESSAGE)

    logger.info("booking created", extra={"ctx": {"booking_id": booking.id, "user_id": user.id}})
    return booking


def cancel_booking(booking_id):
    with transaction.atomic():
        # Lock the row so a payment landing at the same moment waits its turn.
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        try:
            booking.transition_to(Booking.Status.CANCELLED)
        except InvalidTransition as exc:
            raise Conflict(str(exc))

    logger.info("booking cancelled", extra={"ctx": {"booking_id": booking.id}})
    return booking
