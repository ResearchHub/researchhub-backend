from django.db import migrations, models

VALID_LOCK_TYPES = ("FUNDING_CREDIT", "PROMOTIONAL")


def normalize_lock_state(apps, schema_editor):
    Balance = apps.get_model("purchase", "Balance")

    # Locked rows without a recognized category get the restrictive,
    # non-yield-earning default before the constraint is installed.
    Balance.objects.filter(is_locked=True).exclude(
        lock_type__in=VALID_LOCK_TYPES
    ).update(lock_type="FUNDING_CREDIT")
    Balance.objects.filter(is_locked=False).exclude(lock_type__isnull=True).update(
        lock_type=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("purchase", "0058_backfill_balance_lock_type"),
    ]

    operations = [
        migrations.RunPython(normalize_lock_state, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="balance",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        is_locked=True,
                        lock_type__isnull=False,
                        lock_type__in=VALID_LOCK_TYPES,
                    )
                    | models.Q(is_locked=False, lock_type__isnull=True)
                ),
                name="balance_lock_state_valid",
            ),
        ),
    ]
