from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("researchhub_document", "0071_uni_doc_status_pending_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchhubpost",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("DISCUSSION", "DISCUSSION"),
                    ("ELN", "ELN"),
                    ("GRANT", "GRANT"),
                    ("NOTE", "NOTE"),
                    ("PAPER", "PAPER"),
                    ("QUESTION", "QUESTION"),
                    ("PREREGISTRATION", "PREREGISTRATION"),
                    ("REGISTERED_REPORT", "REGISTERED_REPORT"),
                ],
                default="DISCUSSION",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="researchhubunifieddocument",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("DISCUSSION", "DISCUSSION"),
                    ("ELN", "ELN"),
                    ("GRANT", "GRANT"),
                    ("NOTE", "NOTE"),
                    ("PAPER", "PAPER"),
                    ("QUESTION", "QUESTION"),
                    ("PREREGISTRATION", "PREREGISTRATION"),
                    ("REGISTERED_REPORT", "REGISTERED_REPORT"),
                ],
                default="PAPER",
                help_text="Papers are imported from external src. Posts are in-house",
                max_length=32,
            ),
        ),
    ]
