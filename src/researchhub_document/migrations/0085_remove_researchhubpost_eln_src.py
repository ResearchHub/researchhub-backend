from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("researchhub_document", "0084_mark_existing_changelogs"),
    ]

    # State only: the column stays until a follow-up migration drops it, so
    # tasks still running the previous release can keep selecting it during
    # the deploy. The column is nullable, so new rows simply leave it empty.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="researchhubpost",
                    name="eln_src",
                ),
            ],
        ),
    ]
