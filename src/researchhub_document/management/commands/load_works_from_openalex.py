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
    open_alex = OpenAlex()

    oa_ids = []

    for paper in queryset.iterator():
        if not paper.open_alex_raw_json:
            continue

        id_as_url = paper.open_alex_raw_json["id"]
        just_id = id_as_url.split("/")[-1]

        oa_ids.append(just_id)

    works, cursor = open_alex.get_works(openalex_ids=oa_ids)

    process_openalex_works(works)


def process_openalex_work(openalex, openalex_id):
    print(f"Fetching single work with id: {openalex_id}")

    process_openalex_works(
        [
            openalex.get_work(
                openalex_id=openalex_id,
            )
        ]
    )


def process_author_batch(openalex, openalex_author_id, journal):
    print(f"Fetching full author works for author: {openalex_author_id}")

    cursor = "*"

    while cursor:
        print(f"Processing cursor {cursor}")

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
        print(f"Finished fetching all works for author: {openalex_author_id}")

        author = Author.objects.get(
            openalex_ids__contains=[f"https://openalex.org/{openalex_author_id}"]
        )

        author.last_full_fetch_from_openalex = timezone.now()

        author.save()


def process_batch(openalex, journal, page_limit=0, batch_size=100):
    cursor = "*"

    pending_log = PaperFetchLog.objects.filter(
        source=PaperFetchLog.OPENALEX,
        status=PaperFetchLog.PENDING,
        journal=journal,
    ).exists()

    if pending_log:
        print(f"There are pending logs for this journal: {journal}")

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
        journal=journal,
    )

    pages_processed = 0
    total_papers_processed = 0

    while cursor:
        if page_limit and pages_processed >= page_limit:
            break

        print(f"Processing cursor {cursor}")

        works, cursor = openalex.get_works(
            source=journal,
            types=[
                "article",
                "preprint",
                "review",
            ],
            next_cursor=cursor,
            batch_size=batch_size,
        )

        process_openalex_works(works)

        total_papers_processed += len(works)

        pages_processed += 1

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
            type=int,
            help="Paper id to stop at",
        )

        parser.add_argument(
            "--journal",
            type=str,
            help="The paper repository journal ('biorxiv', 'arxiv', etc.) to pull from",
        )

        parser.add_argument(
            "--openalex_id",
            type=str,
            help="The OpenAlex ID to pull",
        )

        parser.add_argument(
            "--openalex_author_id",
            type=str,
            help="The OpenAlex Author ID to pull",
        )

        parser.add_argument(
            "--mode",
            default="backfill",
            type=str,
            help="Either backfill existing docs or load new ones from OpenAlex via filters",
        )

        parser.add_argument(
            "--count",
            type=int,
            help="Limit the number of pages to process",
        )

        parser.add_argument(
            "--batch",
            default=100,
            type=int,
            help="Batch size (number of results) per page (default: 100)",
        )

    def handle(self, *args, **kwargs):
        try:
            if kwargs["mode"] == "backfill":
                current_id = kwargs["start_id"]

                to_id = (
                    kwargs["to_id"] or Paper.objects.all().order_by("-id").first().id
                )

                while True:
                    if current_id > to_id:
                        break

                    next_id = current_id + kwargs["batch"] - 1

                    # Get next "chunk"
                    queryset = Paper.objects.filter(id__gte=current_id, id__lte=next_id)

                    self.stdout.write(
                        f"Processing papers from: {current_id}\nto: "
                        f"{next_id}\ncount: {queryset.count()}"
                    )

                    process_backfill_batch(queryset)

                    current_id += kwargs["batch"]

            elif kwargs["mode"] == "fetch":
                open_alex = OpenAlex()

                if kwargs["openalex_id"]:
                    process_openalex_work(open_alex, kwargs["openalex_id"])

                elif kwargs["openalex_author_id"]:
                    process_author_batch(
                        open_alex, kwargs["openalex_author_id"], kwargs["journal"]
                    )

                else:
                    process_batch(
                        openalex=open_alex,
                        journal=kwargs["journal"],
                        page_limit=kwargs["count"],
                        batch_size=kwargs["batch"],
                    )

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopped by user"))
