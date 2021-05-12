# Generated by Django 2.2 on 2021-05-11 23:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_case', '0002_auto_20210511_2307'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authorclaimcase',
            name='status',
            field=models.CharField(choices=[('CLOSED', 'CLOSED'), ('DENIED', 'DENIED'), ('INITIATED', 'INITIATED'), ('NULLIFIED', 'NULLIFIED'), ('OPEN', 'OPEN')], default='OPEN', max_length=32),
        ),
    ]
