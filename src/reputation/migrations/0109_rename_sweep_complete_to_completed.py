from django.db import migrations, models


def rename_complete_to_completed(apps, schema_editor):
    Deposit = apps.get_model("reputation", "Deposit")
    Deposit.objects.filter(sweep_status="COMPLETE").update(sweep_status="COMPLETED")


def rename_completed_to_complete(apps, schema_editor):
    Deposit = apps.get_model("reputation", "Deposit")
    Deposit.objects.filter(sweep_status="COMPLETED").update(sweep_status="COMPLETE")


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0108_add_index_to_sweep_transfer_id"),
    ]

    operations = [
        migrations.RunPython(
            rename_complete_to_completed,
            reverse_code=rename_completed_to_complete,
        ),
        migrations.AlterField(
            model_name="deposit",
            name="sweep_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PENDING", "Pending"),
                    ("INITIATED", "Initiated"),
                    ("COMPLETED", "Completed"),
                    ("FAILED", "Failed"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
