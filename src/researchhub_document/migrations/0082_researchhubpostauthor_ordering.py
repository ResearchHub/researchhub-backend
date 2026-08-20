import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("researchhub_document", "0081_researchhubpostauthor_position"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="researchhubpostauthor",
            options={"ordering": ["position", "id"]},
        ),
        migrations.AlterField(
            model_name="researchhubpostauthor",
            name="researchhub_post",
            field=models.ForeignKey(
                db_column="researchhubpost_id",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="author_links",
                to="researchhub_document.researchhubpost",
            ),
        ),
    ]
