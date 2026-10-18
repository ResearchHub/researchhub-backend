from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # AddIndexConcurrently cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("researchhub_access_group", "0014_alter_permission_access_type"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                AddIndexConcurrently(
                    model_name="permission",
                    index=models.Index(
                        fields=["content_type", "object_id"],
                        name="access_perm_ct_object_idx",
                    ),
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="permission",
                    index=models.Index(
                        fields=["content_type", "object_id"],
                        name="access_perm_ct_object_idx",
                    ),
                ),
            ],
        ),
    ]
