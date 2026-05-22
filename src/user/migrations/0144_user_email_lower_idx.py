from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    # AddIndexConcurrently cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("user", "0143_delete_userapitoken"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                AddIndexConcurrently(
                    model_name="user",
                    index=models.Index(
                        Lower("email"),
                        name="user_email_lower_idx",
                    ),
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="user",
                    index=models.Index(
                        Lower("email"),
                        name="user_email_lower_idx",
                    ),
                ),
            ],
        ),
    ]
