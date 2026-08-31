import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("research_ai", "0025_proposaldraft_model_ref"),
        ("user", "0151_alter_gatekeeper_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="LLMUsageEvent",
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
                ("feature", models.CharField(db_index=True, max_length=64)),
                ("provider", models.CharField(max_length=64)),
                ("model", models.CharField(max_length=255)),
                ("input_tokens", models.PositiveBigIntegerField(blank=True, null=True)),
                (
                    "output_tokens",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                (
                    "cache_read_tokens",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                (
                    "cache_write_tokens",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                (
                    "cost_microusd",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                (
                    "execution",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="usage_events",
                        to="research_ai.agentexecution",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="research_ai_usage_events",
                        to="user.user",
                    ),
                ),
            ],
            options={"db_table": "research_ai_llm_usage_event"},
        ),
        migrations.AddIndex(
            model_name="llmusageevent",
            index=models.Index(
                fields=["user", "created_date"], name="ra_usage_user_date"
            ),
        ),
    ]
