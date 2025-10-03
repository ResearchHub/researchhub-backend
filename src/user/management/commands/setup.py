import os

import pandas as pd
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management import CommandError, call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from hub.constants import CATEGORY_ORDER
from hub.models import Hub, HubCategory


class Command(BaseCommand):
    help = "Initial setup function for DB seeding that ensures Google is authenticated and that hubs and hub categories exist"

    def handle(self, *args, **options):
        # Ensures the entire setup succeeds, or the DB rolls back to the clean pre-seed state
        with transaction.atomic():
            # Only create if missing, don't return just because this exists
            social_app, created = SocialApp.objects.get_or_create(
                provider="google",
                name="Google",
                defaults={
                    "client_id": "192509748493-5sevdn2gk34kb6i9ehiges3vioui5drm.apps.googleusercontent.com",
                    "secret": "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",
                    "key": "",
                },
            )

            self.stdout.write(
                "Created SocialApp" if created else "SocialApp already exists, skipping"
            )

            site = Site.objects.first()

            if site is None:  # Fallback
                site = Site.objects.create(domain="google.com", name="google")
            else:
                site.domain = "google.com"
                site.name = "google"

                site.save(update_fields=["domain", "name"])

            if not social_app.sites.filter(pk=site.pk).exists():
                social_app.sites.add(site)

            self.stdout.write("Asserting categories...")

            # Idempotent
            call_command("create-categories")

            self.stdout.write("Parsing hub CSV...")

            df = pd.read_csv(
                os.path.join(settings.BASE_DIR, "..", "misc", "hub_hub.csv")
            )

            if "category_id" not in df.columns:
                raise ValueError(
                    "CSV must contain 'category_id' (the position in CATEGORY_ORDER)"
                )

            if "slug" not in df.columns or df["slug"].isnull().any():
                raise ValueError(
                    "CSV must contain a non-null 'slug' for every hub (required for upsert)."
                )

            # Drop unused columns if present
            for col in ("slug_index", "acronym", "hub_image"):
                if col in df.columns:
                    df = df.drop(col, axis=1)

            # Normalize NaN as None so **row works
            df = df.where(pd.notnull(df), None)

            # Build mapping: CSV id (1-based index into CATEGORY_ORDER) -> real HubCategory.id
            id_to_name = {i + 1: name for i, name in enumerate(CATEGORY_ORDER)}
            cats_by_name = {c.category_name: c.id for c in HubCategory.objects.all()}

            def remap_csv_category_id(old_id):
                if old_id is None:
                    return None

                try:
                    return cats_by_name[id_to_name[int(old_id)]]

                except (KeyError, ValueError, TypeError):
                    return None

            df["category_id"] = df["category_id"].map(remap_csv_category_id)

            # Fail fast if any rows didn't map
            bad = df[df["category_id"].isnull()]

            if len(bad):
                raise ValueError(
                    f"{len(bad)} hub rows have unmappable category_id values. "
                    f"First few bad rows: {bad.head(5).to_dict(orient='records')}"
                )

            self.stdout.write("Asserting hubs...")

            objs = []

            # Remove any Nones to prevent errors and so that defaults will be used instead
            for row in df.to_dict(orient="records"):
                objs.append(Hub(**{k: v for k, v in row.items() if v is not None}))

            # Upsert:
            #   - Idempotent relative to the CSV as the source of truth
            #   - If a slug changes on the CSV, the upsert can’t match it to the old row, resulting in a new row
            Hub.objects.bulk_create(
                objs,
                update_conflicts=True,
                update_fields=[
                    "name",
                    "description",
                    "category_id",
                    "is_locked",
                    "is_removed",
                    "discussion_count",
                    "paper_count",
                    "subscriber_count",
                ],
                unique_fields=["slug"],
            )

            def rebuild_search_index():
                self.stdout.write("Rebuilding search index...")

                try:
                    call_command("opensearch", "index", "rebuild", "--force")

                    self.stdout.write(self.style.SUCCESS("Done!"))

                except CommandError as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"(Safe to ignore) OpenSearch indexing failed:\n{e}"
                        )
                    )

            # Run after commit so it sees committed rows
            transaction.on_commit(rebuild_search_index)
