import logging
from datetime import timedelta

from celery import shared_task
from django.db import OperationalError
from django.utils import timezone

from . import services
from .models import WebhookEvent

logger = logging.getLogger(__name__)


@shared_task(
    autoretry_for=(OperationalError,),  # database hiccups: deadlock, timeout, restart
    retry_backoff=True,  # wait 1s, 2s, 4s, ... between attempts
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def process_webhook_event(event_pk):
    services.process_event(event_pk)


@shared_task
def retry_stuck_webhook_events():
    """
    Safety net, run every minute: re-queue events that were stored but never
    applied (for example, the server restarted between the two steps).
    """
    cutoff = timezone.now() - timedelta(minutes=1)
    stuck = WebhookEvent.objects.filter(status=WebhookEvent.Status.RECEIVED, received_at__lt=cutoff)
    event_pks = list(stuck.values_list("pk", flat=True)[:500])
    for event_pk in event_pks:
        process_webhook_event.delay(event_pk)
    if event_pks:
        logger.info("re-queued stuck webhook events", extra={"ctx": {"count": len(event_pks)}})
    return len(event_pks)
