# Generated by Django 2.2 on 2022-04-08 00:29

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('peer_review', '0007_peerreviewinvite_invited_email'),
    ]

    operations = [
        migrations.AlterField(
            model_name='peerreviewinvite',
            name='invited_by_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='peer_review_users_invited', to=settings.AUTH_USER_MODEL),
        ),
    ]
