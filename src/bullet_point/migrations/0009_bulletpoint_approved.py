# Generated by Django 2.2 on 2020-12-17 19:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bullet_point', '0008_merge_20201119_0123'),
    ]

    operations = [
        migrations.AddField(
            model_name='bulletpoint',
            name='approved',
            field=models.BooleanField(default=True),
        ),
    ]
