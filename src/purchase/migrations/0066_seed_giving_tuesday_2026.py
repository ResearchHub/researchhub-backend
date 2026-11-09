from datetime import UTC, datetime

from django.db import migrations

# Midnight US Eastern (UTC-5) on each date.
EARLY_GIFTS_START = datetime(2026, 11, 30, 5, tzinfo=UTC)
GIVING_TUESDAY_START = datetime(2026, 12, 1, 5, tzinfo=UTC)
GIVING_TUESDAY_END = datetime(2026, 12, 2, 5, tzinfo=UTC)


def seed_giving_tuesday_2026(apps, schema_editor):
    GivingCampaign = apps.get_model("purchase", "GivingCampaign")
    GivingChallenge = apps.get_model("purchase", "GivingChallenge")

    campaign = GivingCampaign.objects.create(
        slug="giving-tuesday-2026",
        start_date=GIVING_TUESDAY_START,
        end_date=GIVING_TUESDAY_END,
        goal_usd=300_000,
    )
    GivingChallenge.objects.bulk_create(
        [
            GivingChallenge(
                campaign=campaign,
                kind="UNLOCK",
                name="300 new donors unlock",
                sponsor="Community",
                amount_usd=15_000,
                donor_goal=300,
                first_time_donors_only=True,
                start_date=GIVING_TUESDAY_START,
                end_date=GIVING_TUESDAY_END,
            ),
            GivingChallenge(
                campaign=campaign,
                kind="UNLOCK",
                name="Early-gift unlock",
                sponsor="ResearchHub",
                amount_usd=5_000,
                donor_goal=100,
                start_date=EARLY_GIFTS_START,
                end_date=GIVING_TUESDAY_START,
            ),
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0065_givingcampaign_givingchallenge"),
    ]

    operations = [
        migrations.RunPython(seed_giving_tuesday_2026, migrations.RunPython.noop),
    ]
