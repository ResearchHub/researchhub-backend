# Generated by Django 2.2 on 2022-04-20 14:38

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('discussion', '0046_auto_20220419_1951'),
    ]

    operations = [
        migrations.AlterField(
            model_name='review',
            name='score',
            field=models.FloatField(default=1, null=True, validators=[django.core.validators.MaxValueValidator(10), django.core.validators.MinValueValidator(1)]),
        ),
    ]
