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


PAPER_HEADERS = [
    "ITEM_ID",
    "CREATION_TIMESTAMP",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "discussion_count",
    "hot_score",
    "open_bounty_count",
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

POST_HEADERS = [
    "ITEM_ID",
    "CREATION_TIMESTAMP",
    "item_type",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "discussion_count",
    "hot_score",
    "open_bounty_count",
    "title",
    "slug",
    "authors",
    "updated_timestamp",
    "keywords",
    "hubs",
]

COMMENT_HEADERS = [
    "ITEM_ID",
    "CREATION_TIMESTAMP",
    "item_type",
    "internal_item_id",
    "related_unified_document_id",
    "author",
    "created_by_user_id",
    "peer_review_score",
    "num_replies",
    "hot_score",
    "open_bounty_count",
    "body",
    "related_slug",
    "updated_timestamp",
    "hubs",
]

BOUNTY_HEADERS = [
    "ITEM_ID",
    "CREATION_TIMESTAMP",
    "created_by_user_id",
    "bounty_type",
    "parent_id",
    "internal_item_id",
    "related_unified_document_id",
    "status",
    "expiration_timestamp",
    "is_expiring_soon",
    "num_replies",
    "has_solution",
    "body",
    "related_slug",
    "updated_timestamp",
    "hubs",
]

EXPORT_ITEM_HELPER = {
    "paper": {
        "model": "ResearchhubUnifiedDocument",
        "mapper": map_paper_data,
        "headers": PAPER_HEADERS,
    },
    "post": {
        "model": "ResearchhubUnifiedDocument",
        "mapper": map_post_data,
        "headers": POST_HEADERS,
    },
    "comment": {
        "model": "RhCommentModel",
        "mapper": map_comment_data,
        "headers": COMMENT_HEADERS,
    },
    "bounty": {
        "model": "Bounty",
        "mapper": map_bounty_data,
        "headers": BOUNTY_HEADERS,
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

        # By default we are not resuming and starting from 0
        progress_json = {"current_id": 1, "export_filepath": output_filepath}

        if should_resume:
            progress_json = read_progress_filepath(
                temp_progress_filepath, output_filepath
            )
            output_filepath = progress_json["export_filepath"]
            print("Resuming from ID", progress_json["current_id"])

        queryset = None
        if export_type == "paper":
            queryset = ResearchhubUnifiedDocument.objects.filter(
                document_type__in=["PAPER"],
                is_removed=False,
            )
        elif export_type == "post":
            queryset = ResearchhubUnifiedDocument.objects.filter(
                document_type__in=["DISCUSSION", "QUESTION", "PREREGISTRATION"],
                is_removed=False,
            )
        elif export_type == "comment":
            queryset = RhCommentModel.objects.filter(is_removed=False)
        elif export_type == "bounty":
            queryset = Bounty.objects.all()

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            queryset = queryset.filter(created_date__gte=start_date)

        print(f"Number of records >= {start_date_str}: " + str(len(queryset)))
        print("*********************************************************************")

        export_data_to_csv_in_chunks(
            queryset=queryset,
            chunk_processor=EXPORT_ITEM_HELPER[export_type]["mapper"],
            headers=EXPORT_ITEM_HELPER[export_type]["headers"],
            output_filepath=output_filepath,
            temp_progress_filepath=temp_progress_filepath,
            last_id=progress_json["current_id"],
            on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
        )

        # Cleanup the temp file pointing to our export progress thus far
        # remove_file(TEMP_PROGRESS_FILE)
