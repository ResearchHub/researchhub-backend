from datetime import datetime

from django.core.management.base import BaseCommand

from hub.models import Hub
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
        parser.add_argument("--id", type=str, help="ID of a specific paper.")
        parser.add_argument(
            "--only_user_uploaded", type=str, help="Only user uploaded papers"
        )

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        only_user_uploaded = kwargs["only_user_uploaded"]
        doi = kwargs["doi"]
        id = kwargs["id"]
        open_alex = OpenAlex()

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

            if only_user_uploaded:
                print("Only processing user uploaded papers")
                papers = Paper.objects.filter(
                    created_date__gte=start_date, uploaded_by__isnull=False
                )
            else:
                papers = Paper.objects.filter(created_date__gte=start_date)

            print(f"Found {papers.count()} papers created after {start_date_str}")
        elif doi:
            papers = Paper.objects.filter(doi=doi)
        elif id:
            papers = Paper.objects.filter(id=id)
        else:
            self.stdout.write(self.style.ERROR("Please provide a start date or DOI."))
            return

        num_papers = papers.count()
        for i, paper in enumerate(papers.iterator()):
            try:
                print(
                    "Fetching concepts from OA for paper: "
                    + str(paper.id)
                    + " doi: "
                    + paper.doi
                )
                print("Remaining papers: " + str(num_papers - i))
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
                        hubs = Hub.objects.filter(concept=concept)
                        paper.unified_document.hubs.add(*hubs)

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
