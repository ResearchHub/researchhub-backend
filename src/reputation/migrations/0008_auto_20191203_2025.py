# Generated by Django 2.2.8 on 2019-12-03 20:25

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('reputation', '0007_auto_20191202_2143'),
    ]

    operations = [
        migrations.AddField(
            model_name='distribution',
            name='distributed_date',
            field=models.DateTimeField(default=None, null=True),
        ),
        migrations.AddField(
            model_name='distribution',
            name='distributed_status',
            field=models.CharField(choices=[('failed', 'failed'), ('distributed', 'distributed'), ('pending', 'pending')], default=None, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='distribution',
            name='proof_item_content_type',
            field=models.ForeignKey(default=15, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.ContentType'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='distribution',
            name='proof_item_object_id',
            field=models.PositiveIntegerField(default=3),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='distribution',
            name='updated_date',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
