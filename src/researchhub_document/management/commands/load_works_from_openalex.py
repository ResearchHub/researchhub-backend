from django.core.management.base import BaseCommand

from paper.openalex_util import process_openalex_works
from paper.related_models.paper_model import Paper
from topic.models import Topic
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
            "--mode",
            default="backfill",
            type=str,
            help="Either backfill existing docs or load new ones from OpenAlex via filters",
        )

    def handle(self, *args, **kwargs):
        start_id = kwargs["start_id"]
        to_id = kwargs["to_id"]
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
            while cursor:
                works, cursor = OA.get_works(source_id=source, next_cursor=cursor)
                process_openalex_works(works)
