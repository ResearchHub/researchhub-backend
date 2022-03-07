# Generated by Django 2.2 on 2022-03-05 17:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('paper', '0084_auto_20220209_0543'),
        ('tag', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tag',
            name='papers',
            field=models.ManyToManyField(blank=True, related_name='tags', to='paper.Paper'),
        ),
    ]
