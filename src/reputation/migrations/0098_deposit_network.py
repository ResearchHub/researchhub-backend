# Generated by Django 5.1.4 on 2024-12-20 00:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0097_alter_withdrawal_network"),
    ]

    operations = [
        migrations.AddField(
            model_name="deposit",
            name="network",
            field=models.CharField(
                choices=[("BASE", "Base"), ("ETHEREUM", "Ethereum")],
                db_default="ETHEREUM",
                max_length=10,
            ),
        ),
    ]