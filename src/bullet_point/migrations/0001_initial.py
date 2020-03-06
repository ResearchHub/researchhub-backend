# Generated by Django 2.2.10 on 2020-03-06 21:48

from django.conf import settings
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('paper', '0030_paper_retrieved_from_external_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='BulletPoint',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('updated_date', models.DateTimeField(auto_now=True)),
                ('was_edited', models.BooleanField(default=False, help_text='True if the text was edited after first being created.')),
                ('is_public', models.BooleanField(default=True, help_text='Hides this bullet point from the public but not creator.')),
                ('is_removed', models.BooleanField(default=False, help_text='Hides this bullet point from all.')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, unpack_ipv4=True)),
                ('text', django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True)),
                ('plain_text', models.TextField(blank=True, default='')),
                ('ordinal', models.IntegerField(default=None, null=True)),
                ('ordinal_is_locked', models.BooleanField(default=False)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bullet_points', to=settings.AUTH_USER_MODEL)),
                ('paper', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bullet_points', to='paper.Paper')),
            ],
        ),
        migrations.CreateModel(
            name='Flag',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('updated_date', models.DateTimeField(auto_now=True)),
                ('reason', models.CharField(blank=True, max_length=255)),
                ('bullet_point', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='flags', related_query_name='flag', to='bullet_point.BulletPoint')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bullet_point_flags', related_query_name='bullet_point_flag', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Endorsement',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('updated_date', models.DateTimeField(auto_now=True)),
                ('bullet_point', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='endorsements', related_query_name='endorsement', to='bullet_point.BulletPoint')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bullet_point_endorsements', related_query_name='bullet_point_endorsement', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='flag',
            constraint=models.UniqueConstraint(fields=('bullet_point', 'created_by'), name='unique_bullet_point_flag'),
        ),
        migrations.AddConstraint(
            model_name='endorsement',
            constraint=models.UniqueConstraint(fields=('bullet_point', 'created_by'), name='unique_bullet_point_endorsement'),
        ),
    ]
