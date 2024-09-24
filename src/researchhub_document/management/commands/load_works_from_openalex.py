from django.core.management.base import BaseCommand
from django.utils import timezone

from paper.models import PaperFetchLog
from paper.openalex_util import process_openalex_works
from paper.related_models.paper_model import Paper
from user.related_models.author_model import Author
from utils.openalex import OpenAlex

# To pull papers from bioRxiv use journal param:
# python manage.py load_works_from_openalex --mode backfill --journal biorxiv


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


def process_openalex_work(openalex, openalex_id):
    print("Fetching single work with id: " + openalex_id)
    work = openalex.get_work(
        openalex_id=openalex_id,
    )

    process_openalex_works([work])


def process_author_batch(openalex, openalex_author_id, journal):
    print("Fetching full author works for author: " + openalex_author_id)
    cursor = "*"

    while cursor:
        print("Processing cursor " + str(cursor))
        works, cursor = openalex.get_works(
            source=journal,
            types=[
                "article",
                "preprint",
                "review",
            ],
            next_cursor=cursor,
            openalex_author_id=openalex_author_id,
        )

        process_openalex_works(works)

    if openalex_author_id:
        print("Finished fetching all works for author: " + openalex_author_id)
        full_openalex_id = "https://openalex.org/" + openalex_author_id
        author = Author.objects.get(openalex_ids__contains=[full_openalex_id])
        author.last_full_fetch_from_openalex = timezone.now()
        author.save()


def process_batch(openalex, journal):
    cursor = "*"
    pending_log = PaperFetchLog.objects.filter(
        source=PaperFetchLog.OPENALEX,
        status=PaperFetchLog.PENDING,
        journal=journal,
    ).exists()
    if pending_log:
        print("There are pending logs for this journal")
        return

    last_failed_log = (
        PaperFetchLog.objects.filter(
            source=PaperFetchLog.OPENALEX,
            status__in=[PaperFetchLog.FAILED],
            journal=journal,
        )
        .order_by("-started_date")
        .first()
    )
    if last_failed_log:
        # Start from where we left off
        cursor = last_failed_log.next_cursor

    fetch_log = PaperFetchLog.objects.create(
        source=PaperFetchLog.OPENALEX,
        fetch_type=PaperFetchLog.FETCH_NEW,
        status=PaperFetchLog.PENDING,
        started_date=timezone.now(),
        next_cursor=cursor,
    )

    total_papers_processed = 0
    while cursor:
        print("Processing cursor " + str(cursor))
        works, cursor = openalex.get_works(
            source=journal,
            types=[
                "article",
                "preprint",
                "review",
            ],
            next_cursor=cursor,
        )

        process_openalex_works(works)

        total_papers_processed += len(works)
        fetch_log.total_papers_processed = total_papers_processed
        fetch_log.next_cursor = cursor
        fetch_log.save()

    fetch_log.status = PaperFetchLog.SUCCESS
    fetch_log.finished_date = timezone.now()
    fetch_log.save()


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
            "--journal",
            default=None,
            type=str,
            help="The paper respository journal ('biorxiv', 'arxiv', etc.) to pull from",
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
        journal = kwargs["journal"]
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

            if openalex_id:
                process_openalex_work(OA, openalex_id)
            elif openalex_author_id:
                process_author_batch(OA, openalex_author_id, journal)
            else:
                process_batch(OA, journal)
