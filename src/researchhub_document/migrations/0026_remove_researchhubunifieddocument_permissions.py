# Generated by Django 2.2 on 2021-10-18 17:29

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_document', '0025_auto_20211007_0017'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='researchhubunifieddocument',
            name='permissions',
        ),
    ]
