# Generated by Django 2.2 on 2021-10-07 00:17

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0067_auto_20211005_1901'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='organization',
            name='access_group',
        ),
    ]
