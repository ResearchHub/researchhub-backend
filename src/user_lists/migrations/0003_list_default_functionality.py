from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user_lists', '0002_alter_list_updated_by_alter_list_updated_date_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='list',
            name='name',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='list',
            name='is_default',
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name='list',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_default', True), ('is_removed', False)),
                fields=('created_by',),
                name='unique_default_list_per_user'
            ),
        ),
    ]

