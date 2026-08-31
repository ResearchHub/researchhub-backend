from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("note", "0011_note_selected_grant"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="image",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="note",
            name="preview_img",
            field=models.URLField(blank=True, max_length=2048, null=True),
        ),
    ]
