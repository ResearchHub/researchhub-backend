# Step 3 of zero-downtime migration: Swap the old and new columns

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("paper", "0169_backfill_paper_publish_date_dt"),
    ]

    operations = [
        # Rename old column to _old
        migrations.RenameField(
            model_name="paper",
            old_name="paper_publish_date",
            new_name="paper_publish_date_old",
        ),
        # Rename new column to the original name
        migrations.RenameField(
            model_name="paper",
            old_name="paper_publish_date_dt",
            new_name="paper_publish_date",
        ),
    ]
