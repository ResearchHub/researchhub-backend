from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, and avoids
    # locking the large comment table while the index is built.
    atomic = False

    dependencies = [
        ("researchhub_comment", "0024_alter_rhcommentthreadmodel_updated_date"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="rhcommentmodel",
            index=models.Index(fields=["comment_type"], name="rh_comment_type_idx"),
        ),
    ]
