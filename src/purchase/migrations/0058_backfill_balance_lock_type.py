from django.db import migrations


def backfill_lock_type(apps, schema_editor):
    Balance = apps.get_model("purchase", "Balance")
    Balance.objects.filter(is_locked=True, lock_type__isnull=True).update(
        lock_type="FUNDING_CREDIT"
    )


def reverse_backfill(apps, schema_editor):
    Balance = apps.get_model("purchase", "Balance")
    Balance.objects.filter(
        is_locked=True,
        lock_type="FUNDING_CREDIT",
    ).update(
        lock_type=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("purchase", "0057_balance_lock_type_balance_balance_lock_type_idx"),
    ]

    operations = [
        migrations.RunPython(backfill_lock_type, reverse_backfill),
    ]
