from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0056_alter_purchase_purchase_method"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usdfundraisecontribution",
            name="status",
            field=models.CharField(
                choices=[
                    ("SUBMITTED", "SUBMITTED"),
                    ("CONFIRMED", "CONFIRMED"),
                    ("CANCELLED", "CANCELLED"),
                ],
                default="SUBMITTED",
                help_text="Processual status of the contribution",
                max_length=32,
            ),
        ),
    ]
