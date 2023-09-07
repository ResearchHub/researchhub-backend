# Generated by Django 4.1 on 2023-09-07 13:32

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0019_remove_hubmembership_created_at"),
        ("tag", "0002_unique_concept_openalex_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="concept",
            name="hub",
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="concept",
                to="hub.hub",
            ),
        ),
    ]
