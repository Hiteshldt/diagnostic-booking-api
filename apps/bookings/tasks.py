import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.payments.models import Payment

from .models import Booking

logger = logging.getLogger(__name__)


@shared_task
def expire_unpaid_bookings():
    """
    Runs every few minutes. Cancels PENDING bookings nobody paid for in time.

    Bookings with a payment still in flight are left alone: the webhook will
    settle them.
    """
    cutoff = timezone.now() - timedelta(minutes=settings.BOOKING_PAYMENT_WINDOW_MINUTES)
    expired = (
        Booking.objects.filter(status=Booking.Status.PENDING, created_at__lt=cutoff)
        .exclude(payments__status=Payment.Status.PENDING)
        .update(status=Booking.Status.CANCELLED, updated_at=timezone.now())
    )
    if expired:
        logger.info("expired unpaid bookings", extra={"ctx": {"count": expired}})
    return expired
