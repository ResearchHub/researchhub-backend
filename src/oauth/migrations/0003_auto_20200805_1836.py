# Generated by Django 2.2.14 on 2020-08-05 18:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('oauth', '0002_throttle_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='throttle',
            name='captcha_ident',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='throttle',
            name='throttle_key',
            field=models.CharField(blank=True, default=None, max_length=255, null=True),
        ),
    ]
