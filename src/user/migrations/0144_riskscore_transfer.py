import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0143_delete_userapitoken"),
        ("risk_score", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    state_operations = [
        migrations.CreateModel(
            name="RiskScore",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                ("updated_date", models.DateTimeField(auto_now=True)),
                ("score", models.IntegerField(default=100)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="risk_score",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "risk_score_riskscore",
                "indexes": [
                    models.Index(
                        fields=["score"],
                        name="risk_score_score_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RiskScoreEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_type", models.CharField(max_length=64)),
                ("delta", models.IntegerField()),
                (
                    "source_content_id",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "source_content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="risk_score_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "risk_score_riskscoreevent",
                "ordering": ["-created_date"],
                "indexes": [
                    models.Index(
                        fields=["user", "event_type"],
                        name="risk_event_user_type_idx",
                    ),
                    models.Index(
                        fields=["user", "created_date"],
                        name="risk_event_user_date_idx",
                    ),
                ],
            },
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(state_operations=state_operations),
    ]
