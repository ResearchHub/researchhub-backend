# Generated by Django 4.2.15 on 2024-09-19 17:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0122_alter_authorinstitution_unique_together"),
    ]

    operations = [
        migrations.AlterField(
            model_name="author",
            name="first_name",
            field=models.CharField(max_length=150),
        ),
    ]
