# Generated by Django 2.2 on 2021-08-31 17:41

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('notification', '0007_notification_unified_document'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='notification',
            name='paper',
        ),
    ]
