# Generated by Django 2.2 on 2020-11-20 23:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('paper', '0071_auto_20201120_1956'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paper',
            name='bullet_low_quality',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='paper',
            name='summary_low_quality',
            field=models.BooleanField(default=False),
        ),
    ]
