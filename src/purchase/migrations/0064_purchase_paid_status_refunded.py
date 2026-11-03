from django.db import migrations, models


def backfill_refunded_contributions(apps, schema_editor):
    """
    Closing a fundraise only commits once every contribution has been refunded,
    so contributions on CLOSED fundraises were already refunded.
    """
    ContentType = apps.get_model("contenttypes", "ContentType")
    Fundraise = apps.get_model("purchase", "Fundraise")
    Purchase = apps.get_model("purchase", "Purchase")

    fundraise_ct = ContentType.objects.filter(
        app_label="purchase", model="fundraise"
    ).first()
    if fundraise_ct is None:
        return

    Purchase.objects.filter(
        purchase_type="FUNDRAISE_CONTRIBUTION",
        paid_status="PAID",
        content_type=fundraise_ct,
        object_id__in=Fundraise.objects.filter(status="CLOSED").values("id"),
    ).update(paid_status="REFUNDED")


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("purchase", "0063_delete_support"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aggregatepurchase",
            name="paid_status",
            field=models.CharField(
                choices=[
                    ("FAILED", "FAILED"),
                    ("PAID", "PAID"),
                    ("PENDING", "PENDING"),
                    ("REFUNDED", "REFUNDED"),
                ],
                default="INITIATED",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="paid_status",
            field=models.CharField(
                choices=[
                    ("FAILED", "FAILED"),
                    ("PAID", "PAID"),
                    ("PENDING", "PENDING"),
                    ("REFUNDED", "REFUNDED"),
                ],
                default="INITIATED",
                max_length=255,
                null=True,
            ),
        ),
        # Leave REFUNDED in place on rollback: the reverse cannot tell backfilled
        # rows from later refunds, and marking either PAID again would count
        # refunded contributions as paid.
        migrations.RunPython(
            backfill_refunded_contributions, migrations.RunPython.noop
        ),
    ]
