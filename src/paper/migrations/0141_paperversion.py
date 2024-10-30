# Generated by Django 4.2.15 on 2024-10-23 18:54

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("paper", "0140_delete_asyncpaperupdator"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaperVersion",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version", models.IntegerField(default=1)),
                (
                    "base_doi",
                    models.CharField(
                        blank=True, default=None, max_length=255, null=True
                    ),
                ),
                ("message", models.TextField(blank=True, default=None, null=True)),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                (
                    "paper",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="paper.paper",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        models.Func("base_doi", function="UPPER"),
                        name="paper_version_doi_upper_idx",
                    )
                ],
            },
        ),
    ]