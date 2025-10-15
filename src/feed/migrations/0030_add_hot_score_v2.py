# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0029_optimize_feedentrylatest_subquery"),
    ]

    operations = [
        migrations.AddField(
            model_name="feedentry",
            name="hot_score_v2",
            field=models.IntegerField(
                default=0,
                help_text="New hot score algorithm (v2) for A/B testing",
                db_index=True,
            ),
        ),
        migrations.AddIndex(
            model_name="feedentry",
            index=models.Index(fields=["hot_score_v2"], name="feed_hot_score_v2_idx"),
        ),
    ]
