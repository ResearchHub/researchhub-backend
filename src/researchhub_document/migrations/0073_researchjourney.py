import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_document", "0072_add_registered_report_document_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResearchJourney",
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
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                (
                    "is_in_journal",
                    models.BooleanField(
                        default=False,
                        help_text="Whether this journey is included in the journal feed.",
                    ),
                ),
                (
                    "journal_included_date",
                    models.DateTimeField(
                        blank=True,
                        help_text="When this journey entered the journal feed.",
                        null=True,
                    ),
                ),
                (
                    "grant_post",
                    models.ForeignKey(
                        blank=True,
                        help_text="Grant post that funded this journey, when known.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="grant_research_journeys",
                        to="researchhub_document.researchhubpost",
                    ),
                ),
                (
                    "preregistration_post",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        help_text="Preregistration post that started this journey.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="research_journeys",
                        to="researchhub_document.researchhubpost",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["is_in_journal", "-journal_included_date"],
                        name="journey_journal_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(preregistration_post__isnull=False),
                        fields=("preregistration_post",),
                        name="unique_journey_prereg_post",
                    ),
                ],
            },
        ),
    ]
