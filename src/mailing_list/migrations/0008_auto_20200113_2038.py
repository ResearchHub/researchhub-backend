# Generated by Django 2.2.9 on 2020-01-13 20:38

from django.db import migrations, models
import django.db.models.deletion
import mailing_list.models


class Migration(migrations.Migration):

    dependencies = [
        ('mailing_list', '0007_emailrecipient_next_cursor'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommentSubscription',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('none', models.BooleanField(default=False)),
                ('replies', models.BooleanField(default=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='emailrecipient',
            name='comment_subscription',
            field=mailing_list.models.SubscriptionField(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='email_recipient', to='mailing_list.CommentSubscription'),
        ),
    ]
