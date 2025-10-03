from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from pytz import UTC

from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):
    help = "Seed pre-registrations with fundraises"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=4,
            help="Number of pre-registrations with fundraises to seed (default: 4)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(
            f"Seeding {options['count']} pre-registrations with fundraises..."
        )

        researcher = create_random_authenticated_user(
            "preregistration_fundraise_researcher"
        )

        for i in range(options["count"]):
            preregistration = create_post(
                created_by=researcher,
                document_type=PREREGISTRATION,
                title=f"Research Preregistration {i + 1}",
                renderable_text=f"Detailed research proposal {i + 1}",
            )

            Fundraise.objects.create(
                created_by=researcher,
                unified_document=preregistration.unified_document,
                goal_amount=Decimal(f"{(i + 1) * 10000}.00"),
                goal_currency="USD",
                status=Fundraise.OPEN if i < 2 else Fundraise.COMPLETED,
                end_date=datetime.now(UTC) + timedelta(days=30 * (i + 1)),
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
