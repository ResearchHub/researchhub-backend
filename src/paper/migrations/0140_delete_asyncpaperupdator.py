# Generated by Django 4.2.15 on 2024-10-21 05:40

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("paper", "0139_paper_paper_paper_doi_upper_idx"),
    ]

    operations = [
        migrations.DeleteModel(
            name="AsyncPaperUpdator",
        ),
    ]
