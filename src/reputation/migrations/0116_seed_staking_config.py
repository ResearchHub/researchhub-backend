from django.db import migrations


def seed_staking_config(apps, schema_editor):
    StakingConfig = apps.get_model("reputation", "StakingConfig")
    if not StakingConfig.objects.filter(is_active=True).exists():
        StakingConfig.objects.create(
            emission_per_year=9_500_000,
            circulating_supply=215_052_673,
            staked_fraction=0,
            avg_multiplier=1,
            is_active=True,
        )


def reverse_seed(apps, schema_editor):
    StakingConfig = apps.get_model("reputation", "StakingConfig")
    StakingConfig.objects.filter(is_active=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0115_staking_config_and_accrual"),
    ]

    operations = [
        migrations.RunPython(seed_staking_config, reverse_seed),
    ]
