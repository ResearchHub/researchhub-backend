from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_peer_review", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="editorialfeedbackcategory",
            name="category_code",
            field=models.CharField(
                choices=[
                    ("overall_impact", "overall_impact"),
                    (
                        "importance_significance_innovation",
                        "importance_significance_innovation",
                    ),
                    ("rigor_and_feasibility", "rigor_and_feasibility"),
                    ("additional_review_criteria", "additional_review_criteria"),
                ],
                max_length=64,
            ),
        ),
    ]
