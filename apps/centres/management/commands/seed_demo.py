import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.centres.models import CentreTest, DiagnosticCentre, DiagnosticTest

CENTRES = {
    ("EVE Diagnostics", "Koramangala, Bengaluru"): {"Complete Blood Count": "350.00", "Lipid Profile": "700.00", "Thyroid Panel": "550.00"},
    ("CityCare Labs", "Andheri West, Mumbai"): {"Complete Blood Count": "300.00", "HbA1c": "450.00"},
    ("HealthFirst Imaging", "Connaught Place, New Delhi"): {"Chest X-Ray": "600.00", "MRI Brain": "6500.00"},
}


class Command(BaseCommand):
    help = "Create an admin user and a few demo centres/tests. Safe to run repeatedly."

    def handle(self, *args, **options):
        User = get_user_model()
        email = os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com")
        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(email, os.environ.get("SEED_ADMIN_PASSWORD", "Admin@12345"))

        for (name, location), tests in CENTRES.items():
            centre, _ = DiagnosticCentre.objects.get_or_create(name=name, location=location)
            for test_name, price in tests.items():
                test, _ = DiagnosticTest.objects.get_or_create(name=test_name)
                CentreTest.objects.get_or_create(centre=centre, test=test, defaults={"price": price})

        self.stdout.write(self.style.SUCCESS(f"Seeded demo data (admin: {email})."))
