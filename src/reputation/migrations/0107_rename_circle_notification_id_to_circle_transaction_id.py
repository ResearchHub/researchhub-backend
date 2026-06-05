from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0106_add_sweep_status_to_deposit"),
    ]

    operations = [
        migrations.RenameField(
            model_name="deposit",
            old_name="circle_notification_id",
            new_name="circle_transaction_id",
        ),
    ]
