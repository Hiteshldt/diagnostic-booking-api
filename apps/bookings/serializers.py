from django.utils import timezone
from rest_framework import serializers

from apps.centres.models import CentreTest, DiagnosticCentre, DiagnosticTest

from .models import Booking


class BookingCreateSerializer(serializers.Serializer):
    centre_id = serializers.IntegerField()
    test_id = serializers.IntegerField()
    appointment_at = serializers.DateTimeField()

    def validate_appointment_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Appointment must be in the future.")
        return value

    def validate(self, attrs):
        offering = CentreTest.objects.filter(
            centre_id=attrs["centre_id"], test_id=attrs["test_id"], is_available=True
        ).first()
        if offering is None:
            raise serializers.ValidationError("This centre does not offer this test.")
        attrs["centre_test"] = offering
        return attrs


class _CentreSummary(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticCentre
        fields = ["id", "name", "location"]


class _TestSummary(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "name"]


class BookingSerializer(serializers.ModelSerializer):
    centre = _CentreSummary(source="centre_test.centre", read_only=True)
    test = _TestSummary(source="centre_test.test", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "user_id", "centre", "test", "appointment_at", "amount", "status", "created_at", "updated_at"]
        read_only_fields = fields
