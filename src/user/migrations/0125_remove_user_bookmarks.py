# Generated by Django 4.2.15 on 2024-10-23 07:33

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0124_user_is_official_account"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="bookmarks",
        ),
    ]