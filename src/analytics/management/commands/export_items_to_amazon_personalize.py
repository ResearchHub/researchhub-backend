from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.db.models import Q

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_progress_filepath,
    remove_file,
)
from analytics.utils.analytics_mappers import (
    map_bounty_data,
    map_comment_data,
    map_paper_data,
    map_post_data,
)
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument


def get_temp_progress_file_path(item_type: str, output_path: str):
    return f"{output_path}/{item_type}-item-export-progress.temp.json"


def get_output_file_path(item_type: str, output_path: str):
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"{output_path}/{item_type}-item-export-{date_string}.csv"


def get_error_file_path(item_type: str, output_path: str):
    return f"{output_path}/{item_type}-item-export-errors.txt"


def write_error_to_file(id, error, error_filepath):
    with open(error_filepath, "a") as file:
        file.write(f"ID: {id}, ERROR: {error}\n")


HEADERS = [
    "ITEM_ID",
    "item_type",
    "CREATION_TIMESTAMP",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "discussion_count",
    "hot_score",
    "open_bounty_count",
    "bounty_type",
    "bounty_status",
    "bounty_parent_id",
    "bounty_expiration_timestamp",
    "bounty_is_expiring_soon",
    "bounty_has_solution",
    "body",
    "peer_review_score",
    "title",
    "journal",
    "pdf_license",
    "oa_status",
    "twitter_score",
    "slug",
    "authors",
    "updated_timestamp",
    "publication_timestamp",
    "publication_year",
    "keywords",
    "cited_by_count",
    "citation_percentile_performance",
    "hubs",
    "is_trending_citations",
]


EXPORT_ITEM_HELPER = {
    "paper": {
        "model": "ResearchhubUnifiedDocument",
        "mapper": map_paper_data,
        "headers": HEADERS,
    },
    "post": {
        "model": "ResearchhubUnifiedDocument",
        "mapper": map_post_data,
        "headers": HEADERS,
    },
    "comment": {
        "model": "RhCommentModel",
        "mapper": map_comment_data,
        "headers": HEADERS,
    },
    "bounty": {
        "model": "Bounty",
        "mapper": map_bounty_data,
        "headers": HEADERS,
    },
}


class Command(BaseCommand):
    help = "Export item data to personalize"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start_date",
            type=str,
            help="Start date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--resume",
            type=str,
            help="Resume will start from the last id within the file",
        )
        parser.add_argument(
            "--type", type=str, help="The type you would like to export"
        )
        parser.add_argument("--output_path", type=str, help="The output path")
        parser.add_argument("--from_id", type=str, help="start at a particular id")

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        from_id = kwargs["from_id"]
        should_resume = kwargs["resume"]
        export_type = kwargs["type"]
        output_path = kwargs["output_path"]

        # Related files
        output_filepath = get_output_file_path(export_type, output_path)
        temp_progress_filepath = get_temp_progress_file_path(export_type, output_path)
        error_filepath = get_error_file_path(export_type, output_path)

        # By default we are not resuming and starting from beginning
        progress_json = {"current_id": 0, "export_filepath": output_filepath}

        if should_resume:
            progress_json = read_progress_filepath(
                temp_progress_filepath, output_filepath
            )
            output_filepath = progress_json["export_filepath"]
            print("Resuming from ID", progress_json["current_id"])

        queryset = None
        if export_type == "paper" or export_type == "all":
            from paper.related_models.paper_model import Paper

            queryset = Paper.objects

            if from_id:
                queryset = queryset.filter(id__gte=from_id)

            # The following is meant to filter out papers that are not "COMPLETE"
            queryset = queryset.filter(paper_publish_date__gt=date(2020, 1, 1))

            queryset = (
                queryset.exclude(
                    Q(unified_document_id__isnull=True)
                    | Q(abstract__isnull=True)
                    | Q(title__isnull=True)
                    | Q(is_removed=True)
                    | Q(doi__isnull=True)
                    | Q(open_alex_raw_json__isnull=True)
                    | Q(oa_status="closed")
                )
                .exclude(
                    pdf_url__isnull=True,
                    file__isnull=True,
                )
                .filter(unified_document__hubs__isnull=False)
                .distinct()
            )

            progress_json["current_id"] = from_id

            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                queryset = queryset.filter(created_date__gte=start_date)

            print("Queryset count: ", queryset.count())

            export_data_to_csv_in_chunks(
                queryset=queryset,
                chunk_processor=EXPORT_ITEM_HELPER["paper"]["mapper"],
                headers=EXPORT_ITEM_HELPER["paper"]["headers"],
                output_filepath=output_filepath,
                temp_progress_filepath=temp_progress_filepath,
                last_id=progress_json["current_id"],
                on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
            )

        if export_type == "post" or export_type == "all":
            queryset = ResearchhubUnifiedDocument.objects.filter(
                document_type__in=["DISCUSSION", "QUESTION", "PREREGISTRATION"],
                is_removed=False,
            )

            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                queryset = queryset.filter(created_date__gte=start_date)

            export_data_to_csv_in_chunks(
                queryset=queryset,
                chunk_processor=EXPORT_ITEM_HELPER["post"]["mapper"],
                headers=EXPORT_ITEM_HELPER["post"]["headers"],
                output_filepath=output_filepath,
                temp_progress_filepath=temp_progress_filepath,
                last_id=progress_json["current_id"],
                on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
            )
        if export_type == "comment" or export_type == "all":
            queryset = RhCommentModel.objects.filter(is_removed=False)

            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                queryset = queryset.filter(created_date__gte=start_date)

            export_data_to_csv_in_chunks(
                queryset=queryset,
                chunk_processor=EXPORT_ITEM_HELPER["comment"]["mapper"],
                headers=EXPORT_ITEM_HELPER["comment"]["headers"],
                output_filepath=output_filepath,
                temp_progress_filepath=temp_progress_filepath,
                last_id=progress_json["current_id"],
                on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
            )
        if export_type == "bounty" or export_type == "all":
            queryset = Bounty.objects.all()

            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                queryset = queryset.filter(created_date__gte=start_date)

            export_data_to_csv_in_chunks(
                queryset=queryset,
                chunk_processor=EXPORT_ITEM_HELPER["bounty"]["mapper"],
                headers=EXPORT_ITEM_HELPER["bounty"]["headers"],
                output_filepath=output_filepath,
                temp_progress_filepath=temp_progress_filepath,
                last_id=progress_json["current_id"],
                on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
            )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(temp_progress_filepath)
