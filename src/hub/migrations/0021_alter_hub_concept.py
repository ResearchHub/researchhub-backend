# Generated by Django 4.1 on 2023-09-08 13:51

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tag", "0004_remove_concept_hub"),
        ("hub", "0020_hub_concept"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hub",
            name="concept",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hub",
                to="tag.concept",
            ),
        ),
    ]
