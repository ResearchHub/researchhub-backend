# Generated by Django 2.2 on 2022-04-19 19:43

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('discussion', '0043_review'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='review',
            name='thread',
        ),
    ]
