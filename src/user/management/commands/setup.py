import os

import pandas as pd
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from hub.models import Hub


class Command(BaseCommand):
    def handle(self, *args, **options):
        already_setup = SocialApp.objects.exists()

        if already_setup:
            return "Initial Setup is Already Complete"

        # Keys here are specific for open source community
        social_app = SocialApp.objects.create(
            provider="google",
            name="Google",
            client_id="192509748493-5sevdn2gk34kb6i9ehiges3vioui5drm.apps.googleusercontent.com",
            secret="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",
            key="",
        )
        site = Site.objects.first()
        site.domain = "google.com"
        site.name = "google"
        site.save()
        social_app.sites.add(site)

        manage_py_path = os.path.join(settings.BASE_DIR, "manage.py")

        hub_csv_path = os.path.join(settings.BASE_DIR, "..", "misc", "hub_hub.csv")
        hub_df = pd.read_csv(hub_csv_path)
        hub_df = hub_df.drop("slug_index", axis=1)
        hub_df = hub_df.drop("acronym", axis=1)
        hub_df = hub_df.drop("hub_image", axis=1)
        hub_df = hub_df.drop("category_id", axis=1)
        hubs = [Hub(**row.to_dict()) for _, row in hub_df.iterrows()]
        Hub.objects.bulk_create(hubs)

        os.system(f"python {manage_py_path} search_index --rebuild -f")
