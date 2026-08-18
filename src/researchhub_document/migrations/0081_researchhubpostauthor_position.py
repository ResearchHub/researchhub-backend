import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("researchhub_document", "0080_unifieddocumentsharelink"),
        ("user", "0150_author_user_soft_delete_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ResearchhubPostAuthor",
                    fields=[
                        (
                            "id",
                            models.AutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "researchhub_post",
                            models.ForeignKey(
                                db_column="researchhubpost_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                to="researchhub_document.researchhubpost",
                            ),
                        ),
                        (
                            "author",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="user.author",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "researchhub_document_researchhubpost_authors",
                        "unique_together": {("researchhub_post", "author")},
                    },
                ),
                migrations.AlterField(
                    model_name="researchhubpost",
                    name="authors",
                    field=models.ManyToManyField(
                        related_name="authored_posts",
                        through="researchhub_document.ResearchhubPostAuthor",
                        to="user.author",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="researchhubpostauthor",
            name="position",
            field=models.IntegerField(null=True),
        ),
    ]
