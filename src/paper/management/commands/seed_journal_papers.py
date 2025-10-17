from django.core.management.base import BaseCommand
from django.db import transaction

from paper.related_models.paper_version import PaperVersion
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):
    help = "Seed journal papers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Number of journal papers to seed (default: 5)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"Seeding {options['count']} journal papers...")

        toggle = 0
        researcher = create_random_authenticated_user("journal_paper_researcher")

        for i in range(options["count"]):
            paper = create_paper(uploaded_by=researcher, title=f"Journal Paper {i + 1}")

            paper.version = PaperVersion.objects.create(
                paper=paper,
                journal=PaperVersion.RESEARCHHUB,
                publication_status=(
                    PaperVersion.PUBLISHED if toggle % 2 == 0 else PaperVersion.PREPRINT
                ),
                base_doi=f"10.1234/example{i + 1}.doi",
            )

            paper.save()

            toggle += 1

        self.stdout.write(self.style.SUCCESS("Done!"))
