# Generated by Django 2.2 on 2021-09-28 21:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('invite', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='organizationinvitation',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invited_users', to='user.Organization'),
        ),
    ]
