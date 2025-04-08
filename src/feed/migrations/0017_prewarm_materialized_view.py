# Manually created

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0016_feedentrylatest"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE EXTENSION IF NOT EXISTS pg_prewarm;
                """,
            reverse_sql="""
                DROP EXTENSION IF EXISTS pg_prewarm;
            """,
        ),
        migrations.RunSQL(
            sql="""
                SELECT pg_prewarm('feed_feedentry_popular');
                SELECT pg_prewarm('feed_feedentry_latest');
                """
        ),
    ]
