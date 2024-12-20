# Generated by Django 4.2.15 on 2024-10-18 17:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0093_alter_bounty_bounty_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bounty",
            name="bounty_type",
            field=models.TextField(
                blank=True,
                choices=[
                    ("REVIEW", "REVIEW"),
                    ("ANSWER", "ANSWER"),
                    ("GENERIC_COMMENT", "GENERIC_COMMENT"),
                ],
                null=True,
            ),
        ),
    ]
