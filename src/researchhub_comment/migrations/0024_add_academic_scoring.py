from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_comment', '0023_alter_rhcommentmodel_comment_type_and_more'),
    ]

    operations = [
        # Add fields
        migrations.AddField(
            model_name='rhcommentmodel',
            name='cached_academic_score',
            field=models.FloatField(default=0.0, db_index=True),
        ),
        migrations.AddField(
            model_name='rhcommentmodel',
            name='score_last_calculated',
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Add indexes for performance
        migrations.AddIndex(
            model_name='rhcommentmodel',
            index=models.Index(fields=['-cached_academic_score', '-created_date'], name='researchhub_cachedacad_idx'),
        ),
        migrations.AddIndex(
            model_name='rhcommentmodel',
            index=models.Index(fields=['score_last_calculated'], name='researchhub_scorelastc_idx'),
        ),
        migrations.AddIndex(
            model_name='rhcommentmodel',
            index=models.Index(fields=['is_removed', '-cached_academic_score'], name='researchhub_isremoved_idx'),
        ),
    ]