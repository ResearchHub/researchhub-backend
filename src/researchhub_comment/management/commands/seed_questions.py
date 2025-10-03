from django.core.management.base import BaseCommand
from django.db import transaction

from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import QUESTION
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):
    help = "Seed questions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=3,
            help="Number of questions to seed (default: 3)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"Seeding {options['count']} questions...")

        researcher = create_random_authenticated_user("questions_researcher")

        for i in range(options["count"]):
            create_post(
                created_by=researcher,
                document_type=QUESTION,
                title=f"Research Question {i + 1}",
                renderable_text=f"Question content {i + 1}",
            )

        self.stdout.write(self.style.SUCCESS("Done!"))
