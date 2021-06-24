# Generated by Django 2.2 on 2021-06-04 06:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_document', '0005_auto_20210604_0550'),
    ]

    operations = [
        migrations.AddField(
            model_name='researchhubpost',
            name='document_type',
            field=models.CharField(choices=[('PAPER', 'PAPER'), ('DISCUSSION', 'DISCUSSION'), ('ELN', 'ELN')], default='DISCUSSION', max_length=32),
        ),
    ]
