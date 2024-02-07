import os
from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_last_processed_ids,
    remove_file,
)
from analytics.utils.analytics_mappers import (
    map_comment_data,
    map_paper_data,
    map_post_data,
)
from reputation.related_models.bounty import Bounty
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument

TEMP_PROGRESS_FILE = "./item-export-progress.temp.json"


def get_temp_progress_file_path(item_type: str):
    return f"./{item_type}-item-export-progress.temp.json"


def get_output_file_path(item_type: str):
    return f"./{item_type}-item-export.csv"


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

MODELS_TO_EXPORT = [
    "ResearchhubUnifiedDocument",
    "RhCommentModel",
    "Bounty",
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
    "bounty": "Bounty",
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
            "--force", type=str, help="Force write to file if one already exists"
        )
        parser.add_argument(
            "--type", type=str, help="The type you would like to export"
        )

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        should_resume = kwargs["resume"]
        force = kwargs["force"]
        export_type = kwargs["type"]

        # Check if the file already so we don't accidentally override it and cry over time lost :(
        file_exists = os.path.isfile(get_output_file_path(export_type))
        if file_exists and not should_resume:
            if force:
                remove_file(get_output_file_path(export_type))
            else:
                print(
                    f"File {get_output_file_path(export_type)} already exists. Please delete it or use --force to override it."
                )
                return

        # By default we are not resuming and starting from 0
        last_completed_ids = {key: 0 for key in MODELS_TO_EXPORT}

        if should_resume:
            last_completed_ids = read_last_processed_ids(
                TEMP_PROGRESS_FILE, MODELS_TO_EXPORT
            )
            print("Resuming", last_completed_ids)

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
        elif export_type == "comment":
            queryset = Bounty.objects.filter(is_removed=False)

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            queryset = queryset.filter(created_date__gte=start_date)

        print(f"Number of records >= {start_date_str}: " + str(len(queryset)))
        print("*********************************************************************")

        export_data_to_csv_in_chunks(
            queryset=queryset,
            current_model_to_export=EXPORT_ITEM_HELPER[export_type]["model"],
            all_models_to_export=MODELS_TO_EXPORT,
            chunk_processor=EXPORT_ITEM_HELPER[export_type]["mapper"],
            headers=EXPORT_ITEM_HELPER[export_type]["headers"],
            output_filepath=get_output_file_path(export_type),
            temp_progress_filepath=get_temp_progress_file_path(export_type),
            last_id=last_completed_ids[EXPORT_ITEM_HELPER[export_type]["model"]],
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(TEMP_PROGRESS_FILE)
