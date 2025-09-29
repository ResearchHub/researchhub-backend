# Generated migration to remove sift_risk_score field

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0134_user_user_active_spam_idx'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='sift_risk_score',
        ),
    ]
