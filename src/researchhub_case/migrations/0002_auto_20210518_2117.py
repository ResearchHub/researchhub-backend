# Generated by Django 2.2 on 2021-05-18 21:17

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0059_auto_20210326_0027'),
        ('researchhub_case', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='authorclaimcase',
            name='provided_email',
            field=models.EmailField(default='', help_text='Requestors may use this field to validate themselves with this email', max_length=254),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='authorclaimcase',
            name='target_author',
            field=models.ForeignKey(default=-1, on_delete=django.db.models.deletion.CASCADE, related_name='related_claim_cases', to='user.Author'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='authorclaimcase',
            name='token_generated_time',
            field=models.IntegerField(blank=True, default=None, help_text='Intentionally setting as a int field', null=True),
        ),
        migrations.AddField(
            model_name='authorclaimcase',
            name='validation_attempt_count',
            field=models.IntegerField(default=-1, help_text='Number of attempts to validate themselves given token'),
        ),
        migrations.AddField(
            model_name='authorclaimcase',
            name='validation_token',
            field=models.CharField(blank=True, db_index=True, default=None, help_text='See author_claim_case_post_create_signal', max_length=255, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='authorclaimcase',
            name='creator',
            field=models.ForeignKey(default=-1, on_delete=django.db.models.deletion.CASCADE, related_name='created_cases', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='authorclaimcase',
            name='moderator',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='moderating_cases', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='authorclaimcase',
            name='requestor',
            field=models.ForeignKey(default=-1, on_delete=django.db.models.deletion.CASCADE, related_name='requested_cases', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='authorclaimcase',
            name='status',
            field=models.CharField(choices=[('CLOSED', 'CLOSED'), ('DENIED', 'DENIED'), ('INITIATED', 'INITIATED'), ('NULLIFIED', 'NULLIFIED'), ('OPEN', 'OPEN')], default='INITIATED', max_length=32),
        ),
    ]
