from django.core.management.base import BaseCommand
from django.utils import timezone

from paper.openalex_util import process_openalex_works
from paper.related_models.paper_model import Paper
from topic.models import Topic
from user.related_models.author_model import Author
from utils.openalex import OpenAlex

# To pull papers from bioRxiv use source param:
# python manage.py load_works_from_openalex --mode backfill --source s4306402567


def process_backfill_batch(queryset):
    OA = OpenAlex()

    oa_ids = []
    for paper in queryset.iterator():
        if paper.open_alex_raw_json:
            id_as_url = paper.open_alex_raw_json["id"]
            just_id = id_as_url.split("/")[-1]

            oa_ids.append(just_id)

    works, cursor = OA.get_works(openalex_ids=oa_ids)
    process_openalex_works(works)


class Command(BaseCommand):
    help = "Load works from OpenAlex"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start_id",
            default=1,
            type=int,
            help="Paper start id",
        )
        parser.add_argument(
            "--to_id",
            default=None,
            type=int,
            help="Paper id to stop at",
        )
        parser.add_argument(
            "--source",
            default=None,
            type=str,
            help="The paper respository source to pull from",
        )
        parser.add_argument(
            "--openalex_id",
            default=None,
            type=str,
            help="The OpenAlex ID to pull",
        )
        parser.add_argument(
            "--openalex_author_id",
            default=None,
            type=str,
            help="The OpenAlex Author ID to pull",
        )
        parser.add_argument(
            "--mode",
            default="backfill",
            type=str,
            help="Either backfill existing docs or load new ones from OpenAlex via filters",
        )

    def handle(self, *args, **kwargs):
        start_id = kwargs["start_id"]
        to_id = kwargs["to_id"]
        openalex_id = kwargs["openalex_id"]
        openalex_author_id = kwargs["openalex_author_id"]
        mode = kwargs["mode"]
        source = kwargs["source"]
        batch_size = 100

        if mode == "backfill":
            current_id = start_id
            to_id = to_id or Paper.objects.all().order_by("-id").first().id
            while True:
                if current_id > to_id:
                    break

                # Get next "chunk"
                queryset = Paper.objects.filter(
                    id__gte=current_id, id__lte=(current_id + batch_size - 1)
                )

                print(
                    "processing papers from: ",
                    current_id,
                    " to: ",
                    current_id + batch_size - 1,
                    " count: ",
                    queryset.count(),
                )

                process_backfill_batch(queryset)

                # Update cursor
                current_id += batch_size
        elif mode == "fetch":
            OA = OpenAlex()

            cursor = "*"
            page = 1
            openalex_ids = None
            openalex_types = [
                "article",
                "preprint",
                "review",
            ]

            if openalex_id:
                print("Fetching single work with id: " + openalex_id)
                work = OA.get_work(
                    openalex_id=openalex_id,
                )

                process_openalex_works([work])
                return
            elif openalex_author_id:
                print("Fetching full author works for author: " + openalex_author_id)

            while cursor:
                print("Processing page " + str(page))
                works, cursor = OA.get_works(
                    source_id=source,
                    types=openalex_types,
                    next_cursor=cursor,
                    openalex_ids=openalex_ids,
                    openalex_author_id=openalex_author_id,
                )

                process_openalex_works(works)
                page += 1

            if openalex_author_id:
                print("Finished fetching all works for author: " + openalex_author_id)
                full_openalex_id = "https://openalex.org/" + openalex_author_id
                author = Author.objects.get(openalex_ids__contains=[full_openalex_id])
                author.last_full_fetch_from_openalex = timezone.now()
                author.save()
