# Generated by Django 2.2 on 2022-07-05 23:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_case', '0015_auto_20220422_1541'),
        ('reputation', '0056_bounty_escrow_term'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authorclaimcase',
            name='claimed_rsc',
            field=models.ManyToManyField(blank=True, related_name='claim_case', to='reputation.Escrow'),
        ),
    ]
