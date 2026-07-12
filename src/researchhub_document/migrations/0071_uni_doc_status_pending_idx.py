from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, and avoids
    # locking the large unified-document table while the index is built.
    atomic = False

    dependencies = [
        ("researchhub_document", "0070_researchhubunifieddocument_status_and_more"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="researchhubunifieddocument",
            index=models.Index(
                fields=["status"],
                name="uni_doc_status_pending_idx",
                condition=models.Q(status__in=["PENDING", "DECLINED"]),
            ),
        ),
    ]
