from datetime import datetime

from django.core.management.base import BaseCommand

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


def get_temp_progress_file_path(item_type: str):
    return f"./{item_type}-item-export-progress.temp.json"


def get_output_file_path(item_type: str):
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"./{item_type}-item-export-{date_string}.csv"


def get_error_file_path(item_type: str):
    return f"./{item_type}-item-export-errors.txt"


def write_error_to_file(id, error, error_filepath):
    with open(error_filepath, "a") as file:
        file.write(f"ID: {id}, ERROR: {error}\n")


HEADERS = [
    "ITEM_ID",
    "item_type",  # new
    "CREATION_TIMESTAMP",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "discussion_count",  # need changing
    "hot_score",
    "open_bounty_count",
    "bounty_type",  # new
    "bounty_status",  # new
    "bounty_parent_id",  # new
    "bounty_expiration_timestamp",  # new
    "bounty_is_expiring_soon",  # new
    "bounty_has_solution",  # new
    "body",  # content (abstract, comment body)
    "peer_review_score",  # new
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

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        should_resume = kwargs["resume"]
        export_type = kwargs["type"]

        # Related files
        output_filepath = get_output_file_path(export_type)
        temp_progress_filepath = get_temp_progress_file_path(export_type)
        error_filepath = get_error_file_path(export_type)

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
            queryset = ResearchhubUnifiedDocument.objects.filter(
                document_type__in=["PAPER"],
                is_removed=False,
            )

            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                queryset = queryset.filter(created_date__gte=start_date)

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
