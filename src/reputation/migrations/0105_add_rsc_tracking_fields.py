# Generated migration for funding-based reputation tracking

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reputation', '0104_scorechange_contribution_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='scorechange',
            name='rsc_amount',
            field=models.DecimalField(
                decimal_places=8,
                default=0,
                help_text='Amount of RSC involved in this reputation change (0 for non-RSC contributions)',
                max_digits=19,
            ),
        ),
        migrations.AddField(
            model_name='scorechange',
            name='is_deleted',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text='Whether the content associated with this score change was deleted',
            ),
        ),
        migrations.AddIndex(
            model_name='scorechange',
            index=models.Index(
                fields=['score', 'contribution_type', 'is_deleted'],
                name='scorechange_rsc_idx'
            ),
        ),
    ]

