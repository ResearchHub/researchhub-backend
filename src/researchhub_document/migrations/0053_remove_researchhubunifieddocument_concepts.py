# Generated by Django 4.1 on 2023-09-05 19:44

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_document", "0052_researchhubpost_score"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="researchhubunifieddocument",
            name="concepts",
        ),
    ]
