from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('reputation', '0102_remove_locked_balance_distribution_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='bountysolution',
            name='awarded_by',
            field=models.ForeignKey(
                blank=True,
                help_text='User who awarded this bounty solution',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='awarded_solutions',
                to=settings.AUTH_USER_MODEL
            ),
        ),
    ]