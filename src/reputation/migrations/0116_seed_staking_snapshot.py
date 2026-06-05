from django.db import migrations


def seed_staking_snapshot(apps, schema_editor):
    StakingSnapshot = apps.get_model("reputation", "StakingSnapshot")
    if not StakingSnapshot.objects.exists():
        StakingSnapshot.objects.create(
            emission_per_year=9_500_000,
            circulating_supply=215_052_673,
            staked_fraction=0,
            avg_multiplier=1,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reputation", "0115_stakingsnapshot_stakingyieldaccrual"),
    ]

    operations = [
        migrations.RunPython(seed_staking_snapshot, migrations.RunPython.noop),
    ]
