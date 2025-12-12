from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0104_scorechange_contribution_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="scorechange",
            name="rsc_amount",
            field=models.DecimalField(
                decimal_places=8,
                default=0,
                max_digits=19,
            ),
        ),
        migrations.AddField(
            model_name="scorechange",
            name="is_deleted",
            field=models.BooleanField(
                db_index=True,
                default=False,
            ),
        ),
        migrations.AddField(
            model_name="score",
            name="score_v2",
            field=models.IntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="scorechange",
            index=models.Index(
                fields=["score", "contribution_type", "is_deleted"],
                name="scorechange_rsc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="score",
            index=models.Index(
                fields=["author", "hub", "score_v2"],
                name="idx_score_v2",
            ),
        ),
    ]
