# Generated by Django 2.2 on 2021-03-12 20:48

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('discussion', '0030_auto_20210312_2017'),
    ]

    operations = [
        migrations.AlterField(
            model_name='thread',
            name='metadata',
            field=django.contrib.postgres.fields.jsonb.JSONField(null=True),
        ),
    ]
