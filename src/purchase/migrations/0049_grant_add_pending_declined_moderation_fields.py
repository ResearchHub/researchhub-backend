from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0048_wallet_circle_base_wallet_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="grant",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("OPEN", "Open"),
                    ("CLOSED", "Closed"),
                    ("COMPLETED", "Completed"),
                    ("DECLINED", "Declined"),
                ],
                default="PENDING",
                help_text="Current status of the grant",
                max_length=32,
            ),
        ),
    ]
