# Generated by Django 2.2 on 2020-10-24 00:35

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0048_user_invited_by'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='referral_code',
            field=models.CharField(default=uuid.uuid4, max_length=36, unique=True),
        ),
    ]
