from django.db import migrations


class Migration(migrations.Migration):
    """
    No-op migration.

    This migration was converted to a no-op due to performance issues.
    The data migration is not needed since we have a refresh task.
    """

    dependencies = [
        ("feed", "0034_hotscorev2breakdown"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
