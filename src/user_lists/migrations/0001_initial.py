import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('researchhub_document', '0068_alter_researchhubpost_document_type_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='List',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('updated_date', models.DateTimeField(auto_now=True)),
                ('is_removed', models.BooleanField(default=False)),
                ('is_removed_date', models.DateTimeField(blank=True, default=None, null=True)),
                ('name', models.CharField(max_length=120)),
                ('is_public', models.BooleanField(default=False)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='created_%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='updated_%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='ListItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('updated_date', models.DateTimeField(auto_now=True)),
                ('is_removed', models.BooleanField(default=False)),
                ('is_removed_date', models.DateTimeField(blank=True, default=None, null=True)),
                ('is_public', models.BooleanField(default=False)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='created_%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL)),
                ('parent_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='user_lists.list')),
                ('unified_document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_list_items', to='researchhub_document.researchhubunifieddocument')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='updated_%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_date'],
            },
        ),
        migrations.AddConstraint(
            model_name='list',
            constraint=models.UniqueConstraint(condition=models.Q(('is_removed', False)), fields=('created_by', 'name'), name='unique_not_removed_name_per_user'),
        ),
        migrations.AddConstraint(
            model_name='listitem',
            constraint=models.UniqueConstraint(condition=models.Q(('is_removed', False)), fields=('parent_list', 'unified_document'), name='unique_not_removed_document_per_list'),
        ),
        migrations.AddIndex(
            model_name='list',
            index=models.Index(fields=['created_by', 'is_removed'], name='idx_list_user_removed'),
        ),
        migrations.AddIndex(
            model_name='listitem',
            index=models.Index(fields=['parent_list', 'is_removed'], name='idx_listitem_list_removed'),
        ),
    ]
