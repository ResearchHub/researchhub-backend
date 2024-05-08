from django.core.management.base import BaseCommand

from paper.openalex_util import process_openalex_works
from paper.related_models.paper_model import Paper
from topic.models import Topic
from utils.openalex import OpenAlex


def process_batch(queryset):
    OA = OpenAlex()

    oa_ids = []
    for paper in queryset.iterator():
        if paper.open_alex_raw_json:
            id_as_url = paper.open_alex_raw_json["id"]
            just_id = id_as_url.split("/")[-1]

            oa_ids.append(just_id)

    works, cursor = OA.get_works(openalex_ids=oa_ids)

    process_openalex_works(works)
    # for work in works:
    #     try:

    #         unsaved_paper = OA.build_paper_from_openalex_work(work)
    #     except Exception as e:
    #         print("Failed to build paper:", work["id"], "Exception:", e)
    #         continue

    #     try:
    #         paper = Paper.objects.filter(openalex_id=work["id"])

    #         if paper.exists():
    #             paper.update(**unsaved_paper)
    #         else:
    #             paper = Paper.objects.create(**unsaved_paper)
    #     except Exception as e:
    #         print("Failed to save paper:", work["id"], "Exception:", e)
    #         continue


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
            "--mode",
            default="backfill",
            type=str,
            help="Either backfill existing docs or load new ones from OpenAlex via filters",
        )

    def handle(self, *args, **kwargs):
        start_id = kwargs["start_id"]
        to_id = kwargs["to_id"]
        mode = kwargs["mode"]
        batch_size = 30

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

                process_batch(queryset)

                # Update cursor
                current_id += batch_size
