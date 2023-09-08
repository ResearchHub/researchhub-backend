from datetime import datetime

from django.core.management.base import BaseCommand

from paper.related_models.paper_model import Paper
from tag.models import Concept
from utils.openalex import OpenAlex


class Command(BaseCommand):
    help = "Backfill Concepts for Papers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start_date", type=str, help="Start date in YYYY-MM-DD format."
        )
        parser.add_argument("--doi", type=str, help="DOI of a specific paper.")

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        doi = kwargs["doi"]
        open_alex = OpenAlex()

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            papers = Paper.objects.filter(created_date__gte=start_date)
            print(f"Found {papers.count()} papers created after {start_date_str}")
        elif doi:
            papers = Paper.objects.filter(doi=doi)
        else:
            self.stdout.write(self.style.ERROR("Please provide a start date or DOI."))
            return

        for paper in papers:
            try:
                print(
                    "Fetching concepts from OA for paper: "
                    + str(paper.id)
                    + " doi: "
                    + paper.doi
                )
                result = open_alex.get_data_from_doi(paper.doi)
                if result:
                    paper_concepts = open_alex.hydrate_paper_concepts(
                        result.get("concepts", [])
                    )
                    for paper_concept in paper_concepts:
                        concept = Concept.create_or_update(paper_concept)
                        paper.unified_document.concepts.add(
                            concept,
                            through_defaults={
                                "relevancy_score": paper_concept["score"],
                                "level": paper_concept["level"],
                            },
                        )

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully backfilled concepts for paper {paper.id}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Failed to backfill concepts for paper {paper.id}"
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed to backfill concepts for paper {paper.id}"
                    )
                )
                self.stdout.write(self.style.ERROR(str(e)))

        self.stdout.write(self.style.SUCCESS("Backfill process completed!"))
