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
    ]

