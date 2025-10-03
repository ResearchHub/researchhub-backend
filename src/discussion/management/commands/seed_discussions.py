from django.core.management.base import BaseCommand
from django.db import transaction

from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import DISCUSSION
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):
    help = "Seed discussions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Number of discussions to seed (default: 5)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"Seeding {options['count']} discussions...")

        researcher = create_random_authenticated_user("discussions_researcher")

        for i in range(options["count"]):
            create_post(
                created_by=researcher,
                document_type=DISCUSSION,
                title=f"Discussion Topic {i + 1}",
                renderable_text=f"Discussion content {i + 1}",
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
