from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_lists', '0004_list_is_default'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='list',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_default', True), ('is_removed', False)),
                fields=('created_by',),
                name='unique_default_list_per_user'
            ),
        ),
    ]

