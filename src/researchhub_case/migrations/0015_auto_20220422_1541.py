# Generated by Django 2.2 on 2022-04-22 15:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('researchhub_case', '0014_authorclaimcase_claimed_rsc'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authorclaimcase',
            name='claimed_rsc',
            field=models.ManyToManyField(blank=True, related_name='claim_case', to='researchhub_case.authorclaimcase'),
        ),
    ]
