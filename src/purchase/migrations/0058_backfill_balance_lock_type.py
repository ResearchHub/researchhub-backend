from django.db import migrations

BATCH_SIZE = 5000

# distribution_type -> lock_type for locked rows whose source is a Distribution
DISTRIBUTION_LOCK_TYPES = {
    "PURCHASE": "FUNDING_CREDIT",
    "REFERRAL_BONUS": "REFERRAL_BONUS",
    "STAKING_YIELD": "STAKING_YIELD",
}


def _update_in_batches(queryset, lock_type):
    ids = list(queryset.values_list("id", flat=True))
    model = queryset.model
    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start : start + BATCH_SIZE]
        model.objects.filter(id__in=batch).update(lock_type=lock_type)


def backfill_lock_type(apps, schema_editor):
    Balance = apps.get_model("purchase", "Balance")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Distribution = apps.get_model("reputation", "Distribution")

    locked = Balance.objects.filter(is_locked=True, lock_type__isnull=True)

    dist_ct = ContentType.objects.filter(
        app_label="reputation", model="distribution"
    ).first()
    if dist_ct is not None:
        for distribution_type, lock_type in DISTRIBUTION_LOCK_TYPES.items():
            _update_in_batches(
                locked.filter(
                    content_type=dist_ct,
                    object_id__in=Distribution.objects.filter(
                        distribution_type=distribution_type
                    ).values_list("id", flat=True),
                ),
                lock_type,
            )

    # RSC purchase fee deductions (negative locked rows) are part of the
    # purchased funding credits.
    fee_ct = ContentType.objects.filter(
        app_label="purchase", model="rscpurchasefee"
    ).first()
    if fee_ct is not None:
        _update_in_batches(locked.filter(content_type=fee_ct), "FUNDING_CREDIT")

    # Fundraise contribution movement rows (locked debits/refunds) are not tied
    # to a granting Distribution and intentionally stay NULL — harmless for
    # withdrawal and yield, which key off is_locked / the PROMOTIONAL allowlist.


def reverse_backfill(apps, schema_editor):
    Balance = apps.get_model("purchase", "Balance")
    # Only reset categories this migration backfills; never touch PROMOTIONAL,
    # which controls yield eligibility.
    _update_in_batches(
        Balance.objects.filter(
            is_locked=True,
            lock_type__in=sorted(set(DISTRIBUTION_LOCK_TYPES.values())),
        ),
        None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("purchase", "0057_balance_lock_type_balance_balance_lock_type_idx"),
        ("reputation", "0119_alter_distribution_distribution_type"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(backfill_lock_type, reverse_backfill),
    ]
