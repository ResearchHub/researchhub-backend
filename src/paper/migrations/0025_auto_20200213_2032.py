# Generated by Django 2.2.10 on 2020-02-13 20:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('paper', '0024_auto_20200213_2031'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paper',
            name='file',
            field=models.FileField(blank=True, default=None, null=True, upload_to='uploads/papers/%Y/%m/%d'),
        ),
    ]
