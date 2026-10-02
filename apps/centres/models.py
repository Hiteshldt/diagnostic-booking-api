from django.db import models


class DiagnosticCentre(models.Model):
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["name", "location"], name="uniq_centre_name_location"),
        ]

    def __str__(self):
        return f"{self.name} ({self.location})"


class DiagnosticTest(models.Model):
    """The catalogue of tests (e.g. "Complete Blood Count"), independent of any centre."""

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CentreTest(models.Model):
    """
    "Centre X offers test Y at price Z".

    The same test can cost different amounts at different centres, so the price
    lives on this link table rather than on the test or the centre.
    """

    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.CASCADE, related_name="offerings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="offerings")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ["test__name"]
        constraints = [
            models.UniqueConstraint(fields=["centre", "test"], name="uniq_centre_test"),
            models.CheckConstraint(condition=models.Q(price__gt=0), name="centre_test_price_positive"),
        ]

    def __str__(self):
        return f"{self.test} @ {self.centre}"
