# Generated by Django 4.2.13 on 2024-07-25 18:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notification", "0018_alter_notification_notification_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("DEPRECATED", "DEPRECATED"),
                    ("RSC_WITHDRAWAL_COMPLETE", "RSC_WITHDRAWAL_COMPLETE"),
                    ("RSC_SUPPORT_ON_DOC", "RSC_SUPPORT_ON_DOC"),
                    ("RSC_SUPPORT_ON_DIS", "RSC_SUPPORT_ON_DIS"),
                    ("FLAGGED_CONTENT_VERDICT", "FLAGGED_CONTENT_VERDICT"),
                    ("BOUNTY_EXPIRING_SOON", "BOUNTY_EXPIRING_SOON"),
                    ("DIS_ON_BOUNTY", "DIS_ON_BOUNTY"),
                    ("COMMENT", "COMMENT"),
                    ("COMMENT_ON_COMMENT", "COMMENT_ON_COMMENT"),
                    ("COMMENT_USER_MENTION", "COMMENT_USER_MENTION"),
                    ("BOUNTY_PAYOUT", "BOUNTY_PAYOUT"),
                    ("ACCOUNT_VERIFIED", "ACCOUNT_VERIFIED"),
                    ("PAPER_CLAIMED", "PAPER_CLAIMED"),
                    ("FUNDRAISE_PAYOUT", "FUNDRAISE_PAYOUT"),
                    ("PUBLICATIONS_ADDED", "PUBLICATIONS_ADDED"),
                    ("IDENTITY_VERIFICATION_UPDATED", "IDENTITY_VERIFICATION_UPDATED"),
                    ("PAPER_CLAIM_PAYOUT", "PAPER_CLAIM_PAYOUT"),
                ],
                max_length=32,
                null=True,
            ),
        ),
    ]