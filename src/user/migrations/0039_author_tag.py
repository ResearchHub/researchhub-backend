# Generated by Django 2.2.16 on 2020-09-22 22:41

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0038_auto_20200921_2152'),
    ]

    operations = [
        migrations.AddField(
            model_name='author',
            name='tag',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(blank=True, max_length=32), default=[], size=None),
            preserve_default=False,
        ),
    ]
