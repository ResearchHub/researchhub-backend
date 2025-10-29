# Generated manually for performance optimization
# Adds index to grant_contacts M2M through table to speed up contacts query

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0038_add_composite_indexes_for_performance"),
    ]

    operations = [
        # Add composite index on (grant_id, user_id) for the M2M through table
        # This helps speed up the grant.contacts query significantly (was 450ms)
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS purchase_grant_contacts_grant_user_idx ON purchase_grant_contacts (grant_id, user_id);",
            reverse_sql="DROP INDEX IF EXISTS purchase_grant_contacts_grant_user_idx;",
        ),
    ]

