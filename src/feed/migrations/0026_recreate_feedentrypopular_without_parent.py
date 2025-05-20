# Manually created

from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0025_remove_feedentry_unique_feed_entry_and_more"),
    ]

    def get_sql():
        # Limit data to the last 30 days in production
        limit_data = (
            "WHERE fe.created_date >= (NOW() - INTERVAL '30 days')"
            if settings.PRODUCTION
            else ""
        )

        sql = f"""
                CREATE MATERIALIZED VIEW feed_feedentry_popular AS
                SELECT
                    fe.id,
                    fe.content_type_id,
                    fe.object_id,
                    fe.content,
                    fe.metrics,
                    fe.action,
                    fe.action_date,
                    fe.user_id,
                    fe.unified_document_id,
                    fe.hot_score,
                    fe.created_date,
                    fe.updated_date
                FROM
                    feed_feedentry fe
                {limit_data}
                ORDER BY
                    fe.hot_score DESC;

            CREATE UNIQUE INDEX feed_feedentry_popular_unique_idx ON feed_feedentry_popular (id);
            CREATE INDEX feed_feedentry_popular_hotscore_idx ON feed_feedentry_popular (hot_score DESC);
            CREATE INDEX feed_feedentry_popular_action_date_idx ON feed_feedentry_popular (action_date DESC);
            """.format(
            limit_data
        )
        return sql

    operations = [
        migrations.RunSQL(
            "DROP MATERIALIZED VIEW IF EXISTS feed_feedentry_popular;",
        ),
        migrations.RunSQL(
            sql=get_sql(),
        ),
    ]
