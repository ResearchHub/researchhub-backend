# Generated by Django 5.1.4 on 2024-12-20 00:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institution", "0005_alter_institution_associated_institutions_and_more"),
        ("paper", "0150_remove_authorship_unique_paper_author_and_more"),
        ("user", "0127_author_user_author_openalex_ids_idx"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="authorship",
            name="paper_authorship_paper_author_unique",
        ),
        migrations.AddConstraint(
            model_name="authorship",
            constraint=models.UniqueConstraint(
                fields=("paper", "author"), name="unique_paper_author"
            ),
        ),
    ]