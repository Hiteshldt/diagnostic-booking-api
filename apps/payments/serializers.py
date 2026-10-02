from rest_framework import serializers

from .models import Payment


class PaymentCreateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()
    simulate = serializers.ChoiceField(
        choices=["success", "failed", "pending"],
        required=False,
        help_text="Force the simulated outcome. Omit for a random SUCCESS/FAILED. "
        "'pending' leaves the payment open for the webhook to settle.",
    )


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "booking_id", "amount", "status", "failure_reason", "created_at", "updated_at"]
        read_only_fields = fields


class WebhookSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=255)
    payment_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=[Payment.Status.SUCCESS, Payment.Status.FAILED])
    failure_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class WebhookResponseSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    status = serializers.CharField()
    duplicate = serializers.BooleanField()
