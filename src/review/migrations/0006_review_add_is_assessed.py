from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("review", "0005_peerreview_peerreview_unique_paper_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="is_assessed",
            field=models.BooleanField(default=False),
        ),
    ]
