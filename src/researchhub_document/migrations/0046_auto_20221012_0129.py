# Generated by Django 2.2 on 2022-10-12 01:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_document', '0045_documentfilter_hubs_excluded'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='documentfilter',
            name='hubs_excluded',
        ),
        migrations.AddField(
            model_name='documentfilter',
            name='is_excluded',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
