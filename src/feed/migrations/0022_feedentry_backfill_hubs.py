# Manually created

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0021_feedentry_hubs_feedentry_feed_hubs_gin_idx"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Get content type ID for hub
            WITH hub_type AS (
                SELECT id
                FROM django_content_type
                WHERE app_label='hub' AND model='hub'
            ),
            -- Aggregate hubs for each feed entry
            hubs_per_entry AS (
                SELECT
                    fe.object_id,
                    ARRAY_AGG(fe.parent_object_id ORDER BY fe.parent_object_id) AS hub_ids
                FROM feed_feedentry fe
                WHERE fe.parent_content_type_id = (SELECT id FROM hub_type)
                GROUP BY fe.object_id, fe.content_type_id
            )
            -- Update every row with the aggregated hubs
            UPDATE feed_feedentry AS fe
            SET hubs = h.hub_ids
            FROM hubs_per_entry AS h
            WHERE fe.parent_content_type_id = (SELECT id FROM hub_type)
            AND fe.object_id = h.object_id
            """,
        )
    ]
