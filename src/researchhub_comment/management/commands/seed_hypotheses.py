from django.core.management.base import BaseCommand
from django.db import transaction

from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import HYPOTHESIS
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):
    help = "Seed hypotheses"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=3,
            help="Number of hypotheses to seed (default: 3)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"Seeding {options['count']} hypotheses...")

        researcher = create_random_authenticated_user("hypothesis_researcher")

        for i in range(options["count"]):
            create_post(
                created_by=researcher,
                document_type=HYPOTHESIS,
                title=f"Hypothesis {i + 1}",
                renderable_text=f"Hypothesis content {i + 1}",
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
