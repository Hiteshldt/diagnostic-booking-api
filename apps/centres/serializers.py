from decimal import Decimal

from rest_framework import serializers

from .models import CentreTest, DiagnosticCentre, DiagnosticTest


class DiagnosticTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "name", "description"]


class CentreTestSerializer(serializers.ModelSerializer):
    """A test offered by a centre, with that centre's price."""

    test_id = serializers.PrimaryKeyRelatedField(source="test", queryset=DiagnosticTest.objects.all())
    name = serializers.CharField(source="test.name", read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:
        model = CentreTest
        fields = ["id", "test_id", "name", "price", "is_available"]


class CentreSerializer(serializers.ModelSerializer):
    tests = CentreTestSerializer(source="offerings", many=True, read_only=True)

    class Meta:
        model = DiagnosticCentre
        fields = ["id", "name", "location", "tests"]

    def validate(self, attrs):
        name = attrs.get("name", getattr(self.instance, "name", None))
        location = attrs.get("location", getattr(self.instance, "location", None))
        clash = DiagnosticCentre.objects.filter(name=name, location=location)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A centre with this name and location already exists.")
        return attrs
