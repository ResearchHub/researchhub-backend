from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def _normalize_author_positions(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Normalize every post's author positions to a contiguous sequence."""
    PostAuthor = apps.get_model("researchhub_document", "ResearchhubPostAuthor")
    quote_name = schema_editor.quote_name
    table = quote_name(PostAuthor._meta.db_table)
    id_column = quote_name(PostAuthor._meta.pk.column)
    post_column = quote_name(PostAuthor._meta.get_field("researchhub_post").column)
    position_column = quote_name(PostAuthor._meta.get_field("position").column)

    schema_editor.execute(
        f"""
        WITH ranked AS (
            SELECT
                {id_column} AS row_id,
                CAST(
                    ROW_NUMBER() OVER (
                        PARTITION BY {post_column}
                        ORDER BY {position_column} ASC NULLS LAST, {id_column}
                    ) AS integer
                ) AS normalized_position
            FROM {table}
        )
        UPDATE {table} AS links
        SET {position_column} = ranked.normalized_position
        FROM ranked
        WHERE links.{id_column} = ranked.row_id
          AND links.{position_column} IS DISTINCT FROM ranked.normalized_position
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("researchhub_document", "0081_researchhubpostauthor_position"),
    ]

    operations = [
        migrations.RunPython(
            _normalize_author_positions,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="researchhubpostauthor",
            name="position",
            field=models.IntegerField(),
        ),
        migrations.AddConstraint(
            model_name="researchhubpostauthor",
            constraint=models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="researchhubpostauthor_position_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="researchhubpostauthor",
            constraint=models.UniqueConstraint(
                fields=("researchhub_post", "position"),
                name="unique_researchhubpostauthor_position",
            ),
        ),
    ]
