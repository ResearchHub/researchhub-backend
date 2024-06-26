"""
The purpose of this script is to enrich local papers with OpenAlex data.
Such data includes topics, subfields, etc...
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from paper.openalex_util import process_openalex_works
from paper.related_models.paper_model import Paper
from researchhub_case.related_models.author_claim_case_model import AuthorClaimCase
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from utils.openalex import OpenAlex


class Command(BaseCommand):
    help = "Associate hubs with subfields (Used for rep)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--id",
            default=None,
            type=int,
            help="Run for specific paper",
        )

        parser.add_argument(
            "--start_id",
            default=None,
            type=int,
            help="Paper start id",
        )

        parser.add_argument(
            "--interacted_content_only",
            default=False,
            type=bool,
            help="If used, only content that has been interacted with will be processed (e.g. papers associated with comments instaed of all papers)",
        )

    def handle(self, *args, **kwargs):
        OA = OpenAlex()
        papers = Paper.objects.all()

        if kwargs["id"]:
            papers = papers.filter(id=kwargs["id"])
        elif kwargs["start_id"]:
            papers = papers.filter(id__gte=kwargs["start_id"])

        if kwargs["interacted_content_only"]:
            # First, get all papers associated with comments
            content_type = ContentType.objects.get_for_model(Paper)
            all_threads = RhCommentThreadModel.objects.filter(content_type=content_type)
            unique_paper_ids = list(set([thread.object_id for thread in all_threads]))

            print(f"Total papers associated w/comments: {len(unique_paper_ids)}")
            papers = papers.filter(id__in=unique_paper_ids)

            # Get all claimed papers
            claimed = Paper.objects.filter(authors__user__isnull=False)
            print(f"Total claimed papers: {claimed.count()}")
            papers = papers.union(claimed)

        for paper in papers:
            try:
                work = OA.get_data_from_doi(paper.doi)
                process_openalex_works([work])
            except Exception as e:
                print(f"Error processing paper {paper.id}: {e}")
