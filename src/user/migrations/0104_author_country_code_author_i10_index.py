# Generated by Django 4.1 on 2024-05-17 01:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0103_remove_author_linkedin_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="author",
            name="country_code",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="author",
            name="i10_index",
            field=models.IntegerField(default=0),
        ),
    ]
