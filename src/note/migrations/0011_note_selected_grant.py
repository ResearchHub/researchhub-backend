import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("note", "0010_notecontent_created_by_notecontent_created_via_and_more"),
        ("purchase", "0060_alter_rscexchangerate_price_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="selected_grant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="draft_notes",
                to="purchase.grant",
            ),
        ),
    ]
