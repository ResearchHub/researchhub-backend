from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from hub.models import Hub
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):
    help = "Seed grants"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=3,
            help="Number of grants to seed (default: 3)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"Seeding {options['count']} grants...")

        moderator = create_random_authenticated_user("dev_moderator", moderator=True)

        hub, created = Hub.objects.get_or_create(
            name="Grants",
            defaults={"description": "Research grants and funding opportunities"},
        )

        for i in range(options["count"]):
            grant_post = create_post(
                created_by=moderator,
                document_type=GRANT,
                title=f"Research Grant {i + 1}",
            )

            grant_post.unified_document.hubs.add(hub)

            Grant.objects.create(
                created_by=moderator,
                unified_document=grant_post.unified_document,
                amount=Decimal(f"{(i + 1) * 25000}.00"),
                currency="USD",
                organization=f"Foundation {i + 1}",
                description=f"Research grant {i + 1}",
                status=Grant.OPEN,
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
