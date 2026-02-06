# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0043_usdfundraisecontribution_destination_org_id_and_more"),
    ]

    operations = [
        migrations.DeleteModel(
            name="UsdBalance",
        ),
    ]
