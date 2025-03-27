# Generated by Django 5.1.5 on 2025-03-26 16:38

import django.core.serializers.json
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0010_feedentry_content"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feedentry",
            name="content",
            field=models.JSONField(
                db_comment="A serialized JSON representation of the item.",
                default=dict,
                encoder=django.core.serializers.json.DjangoJSONEncoder,
            ),
        ),
    ]
