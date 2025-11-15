from django.db import migrations


def migrate_breakdown_data(apps, schema_editor):
    """
    Move hot_score_v2_breakdown data from FeedEntry to HotScoreV2Breakdown table.

    This migration copies all existing breakdown data from the JSONField
    to the new separate table.
    """
    FeedEntry = apps.get_model("feed", "FeedEntry")
    HotScoreV2Breakdown = apps.get_model("feed", "HotScoreV2Breakdown")

    # Get all entries that have non-empty breakdown data
    entries = FeedEntry.objects.filter(hot_score_v2_breakdown__isnull=False).exclude(
        hot_score_v2_breakdown={}
    )

    total = entries.count()
    if total == 0:
        print("No breakdown data to migrate.")
        return

    print(f"Migrating {total} breakdown records...")

    # Process in batches to avoid memory issues
    batch_size = 1000
    breakdowns_to_create = []

    for i, entry in enumerate(entries, 1):
        if entry.hot_score_v2_breakdown:
            breakdowns_to_create.append(
                HotScoreV2Breakdown(
                    feed_entry_id=entry.id,
                    breakdown_data=entry.hot_score_v2_breakdown,
                    created_date=entry.created_date,
                    updated_date=entry.updated_date,
                )
            )

        # Bulk create when batch is full
        if len(breakdowns_to_create) >= batch_size:
            HotScoreV2Breakdown.objects.bulk_create(
                breakdowns_to_create, ignore_conflicts=True
            )
            print(f"Migrated {i} of {total} records...")
            breakdowns_to_create = []

    # Create remaining records
    if breakdowns_to_create:
        HotScoreV2Breakdown.objects.bulk_create(
            breakdowns_to_create, ignore_conflicts=True
        )

    print(f"Migration complete! Migrated {total} records.")


def reverse_migrate(apps, schema_editor):
    """
    Reverse migration: move data back to FeedEntry.

    This allows rolling back the migration if needed.
    """
    FeedEntry = apps.get_model("feed", "FeedEntry")
    HotScoreV2Breakdown = apps.get_model("feed", "HotScoreV2Breakdown")

    for breakdown in HotScoreV2Breakdown.objects.all():
        FeedEntry.objects.filter(id=breakdown.feed_entry_id).update(
            hot_score_v2_breakdown=breakdown.breakdown_data
        )


class Migration(migrations.Migration):
    dependencies = [
        ("feed", "0034_hotscorev2breakdown"),
    ]

    operations = [
        migrations.RunPython(
            migrate_breakdown_data,
            reverse_migrate,
        ),
    ]
