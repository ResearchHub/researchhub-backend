# Generated by Django 2.2 on 2020-11-07 01:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('summary', '0010_summary_is_removed'),
    ]

    operations = [
        migrations.AddField(
            model_name='summary',
            name='sift_risk_score',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
