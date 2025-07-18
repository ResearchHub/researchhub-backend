# Generated by Django 5.1.5 on 2025-06-25 19:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_comment", "0022_alter_rhcommentmodel_comment_type_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rhcommentmodel",
            name="comment_type",
            field=models.CharField(
                choices=[
                    ("AUTHOR_UPDATE", "AUTHOR_UPDATE"),
                    ("GENERIC_COMMENT", "GENERIC_COMMENT"),
                    ("INNER_CONTENT_COMMENT", "INNER_CONTENT_COMMENT"),
                    ("ANSWER", "ANSWER"),
                    ("REVIEW", "REVIEW"),
                    ("PEER_REVIEW", "PEER_REVIEW"),
                    ("SUMMARY", "SUMMARY"),
                    ("REPLICABILITY_COMMENT", "REPLICABILITY_COMMENT"),
                    ("AUTHOR_UPDATE", "AUTHOR_UPDATE"),
                ],
                default="GENERIC_COMMENT",
                max_length=144,
            ),
        ),
        migrations.AlterField(
            model_name="rhcommentthreadmodel",
            name="thread_type",
            field=models.CharField(
                choices=[
                    ("AUTHOR_UPDATE", "AUTHOR_UPDATE"),
                    ("GENERIC_COMMENT", "GENERIC_COMMENT"),
                    ("INNER_CONTENT_COMMENT", "INNER_CONTENT_COMMENT"),
                    ("ANSWER", "ANSWER"),
                    ("REVIEW", "REVIEW"),
                    ("PEER_REVIEW", "PEER_REVIEW"),
                    ("SUMMARY", "SUMMARY"),
                    ("REPLICABILITY_COMMENT", "REPLICABILITY_COMMENT"),
                    ("AUTHOR_UPDATE", "AUTHOR_UPDATE"),
                ],
                default="GENERIC_COMMENT",
                max_length=144,
            ),
        ),
    ]
