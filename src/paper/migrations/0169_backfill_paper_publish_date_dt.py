# Step 2 of zero-downtime migration: Backfill data from paper_publish_date to paper_publish_date_dt

from django.db import migrations
from django.db.models import F


def backfill_paper_publish_date(apps, schema_editor):
    """
    Backfill paper_publish_date_dt from paper_publish_date in batches
    to avoid long-running locks on the table.
    """
    Paper = apps.get_model("paper", "Paper")

    batch_size = 10000
    updated = 0

    while True:
        # Update in batches to avoid long locks
        batch = Paper.objects.filter(
            paper_publish_date__isnull=False, paper_publish_date_dt__isnull=True
        )[:batch_size]

        ids_to_update = list(batch.values_list("id", flat=True))

        if not ids_to_update:
            break

        # Use F() expression to copy date to datetime
        # PostgreSQL will automatically convert date to timestamp at midnight
        Paper.objects.filter(id__in=ids_to_update).update(
            paper_publish_date_dt=F("paper_publish_date")
        )

        updated += len(ids_to_update)


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("paper", "0168_paper_paper_publish_date_dt_and_more"),
    ]

    operations = [
        migrations.RunPython(
            backfill_paper_publish_date,
            reverse_backfill,
        ),
    ]
