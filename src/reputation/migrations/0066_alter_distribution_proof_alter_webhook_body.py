# Generated by Django 4.1 on 2022-11-11 00:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0065_auto_20221109_1719"),
    ]

    operations = [
        migrations.AlterField(
            model_name="distribution",
            name="proof",
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name="webhook",
            name="body",
            field=models.JSONField(blank=True),
        ),
    ]