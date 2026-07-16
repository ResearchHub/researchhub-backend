import csv
import os

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from hub.models import Hub


class Command(BaseCommand):
    def handle(self, *args, **options):
        already_setup = SocialApp.objects.exists()

        if already_setup:
            return "Initial Setup is Already Complete"

        social_app = SocialApp.objects.create(
            provider="google",
            name="Google",
            client_id=getattr(settings, "GOOGLE_CLIENT_ID", ""),
            secret=getattr(settings, "GOOGLE_CLIENT_SECRET", ""),
            key="",
        )
        site = Site.objects.first()
        site.domain = "google.com"
        site.name = "google"
        site.save()
        social_app.sites.add(site)

        orcid_app = SocialApp.objects.create(
            provider=OrcidProvider.id,
            name="ORCID",
            client_id=getattr(settings, "ORCID_CLIENT_ID", ""),
            secret=getattr(settings, "ORCID_CLIENT_SECRET", ""),
            key="",
        )
        orcid_app.sites.add(site)

        manage_py_path = os.path.join(settings.BASE_DIR, "manage.py")

        hub_csv_path = os.path.join(settings.BASE_DIR, "..", "misc", "hub_hub.csv")
        hubs = []
        with open(hub_csv_path, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                for column in ("slug_index", "acronym", "hub_image", "category_id"):
                    del row[column]
                row["is_locked"] = row["is_locked"] == "TRUE"
                row["is_removed"] = row["is_removed"] == "TRUE"
                hubs.append(Hub(**row))
        Hub.objects.bulk_create(hubs)

        os.system(f"python {manage_py_path} search_index --rebuild -f")
