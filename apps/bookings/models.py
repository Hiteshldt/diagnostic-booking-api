import uuid

from django.conf import settings
from django.db import models


class InvalidTransition(Exception):
    pass


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"  # created, waiting for payment
        CONFIRMED = "CONFIRMED"  # paid
        FAILED = "FAILED"  # payment failed
        CANCELLED = "CANCELLED"  # cancelled by the user, or expired unpaid

    # The booking state machine: which statuses each status may move to.
    # FAILED and CANCELLED are final.
    TRANSITIONS = {
        Status.PENDING: {Status.CONFIRMED, Status.FAILED, Status.CANCELLED},
        Status.CONFIRMED: {Status.CANCELLED},
        Status.FAILED: set(),
        Status.CANCELLED: set(),
    }

    # A UUID, so booking ids cannot be guessed by counting up.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    # Points at "centre offers test", which pins down both the centre and the
    # test and makes it impossible to book a test the centre does not offer.
    centre_test = models.ForeignKey("centres.CentreTest", on_delete=models.PROTECT, related_name="bookings")
    appointment_at = models.DateTimeField()
    # Copied from the price at booking time, so later price changes do not alter it.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="booking_user_created_idx"),
            models.Index(fields=["status", "created_at"], name="booking_status_created_idx"),
        ]
        constraints = [
            # The database itself refuses a second live booking for the same
            # user + test + time, even if two requests arrive simultaneously.
            models.UniqueConstraint(
                fields=["user", "centre_test", "appointment_at"],
                condition=models.Q(status__in=["PENDING", "CONFIRMED"]),
                name="uniq_active_booking_per_slot",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="booking_amount_positive"),
        ]

    def transition_to(self, new_status):
        if new_status not in self.TRANSITIONS[self.status]:
            raise InvalidTransition(f"A {self.status} booking cannot become {new_status}.")
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])
