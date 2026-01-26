from django.db import migrations


def add_initial_rsc_purchase_fee(apps, schema_editor):
    RscPurchaseFee = apps.get_model("purchase", "RscPurchaseFee")
    RscPurchaseFee.objects.create(rh_pct=0.07, dao_pct=0.00)


class Migration(migrations.Migration):
    dependencies = [
        ("purchase", "0040_rscpurchasefee"),
    ]

    operations = [
        migrations.RunPython(add_initial_rsc_purchase_fee),
    ]
