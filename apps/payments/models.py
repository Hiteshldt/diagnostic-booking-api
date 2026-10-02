import uuid

from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"  # sent to the provider, result not known yet
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey("bookings.Booking", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            # At most one in-flight or successful payment per booking, enforced
            # by the database: a booking can never be charged twice.
            models.UniqueConstraint(
                fields=["booking"],
                condition=models.Q(status__in=["PENDING", "SUCCESS"]),
                name="uniq_active_payment_per_booking",
            ),
        ]


class WebhookEvent(models.Model):
    """
    A record of every webhook event we have been sent.

    `event_id` is unique, and that is what makes the webhook idempotent: a
    repeated delivery finds the existing row instead of being applied again.
    """

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED"  # stored, not applied yet
        PROCESSED = "PROCESSED"  # applied to the payment
        IGNORED = "IGNORED"  # valid, but the payment was already settled
        FAILED = "FAILED"  # could not be applied (e.g. unknown payment)

    FINAL_STATUSES = {Status.PROCESSED, Status.IGNORED}

    event_id = models.CharField(max_length=255, unique=True)
    payment = models.ForeignKey(Payment, null=True, on_delete=models.PROTECT, related_name="webhook_events")
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED)
    note = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=["status", "received_at"], name="webhook_status_received_idx")]

    @property
    def is_final(self):
        return self.status in self.FINAL_STATUSES
