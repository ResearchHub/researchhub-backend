from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_lists', '0003_alter_list_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='list',
            name='is_default',
            field=models.BooleanField(default=False),
        ),
    ]

