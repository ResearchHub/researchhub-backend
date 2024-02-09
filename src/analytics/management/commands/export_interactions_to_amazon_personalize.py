from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_progress_filepath,
    remove_file,
)
from analytics.utils.analytics_mappers import map_action_data, map_claim_data
from researchhub_case.related_models.author_claim_case_model import AuthorClaimCase
from user.models import Action

EXPORT_FILE_HEADERS = [
    "ITEM_ID",
    "EVENT_TYPE",
    "TIMESTAMP",
    "EVENT_VALUE",
    "USER_ID",
    "internal_id",
    "unified_document_id",
    "hubs",
]


def get_temp_progress_file_path():
    return f"./interaction-export-progress.temp.json"


def get_output_file_path():
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"./interaction-export-{date_string}.csv"


def get_error_file_path():
    return f"./interaction-export-errors.txt"


def write_error_to_file(id, error, error_filepath):
    with open(error_filepath, "a") as file:
        file.write(f"ID: {id}, ERROR: {error}\n")


class Command(BaseCommand):
    help = "Export interaction data to personalize"

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

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        should_resume = kwargs["resume"]

        # Related files
        output_filepath = get_output_file_path()
        temp_progress_filepath = get_temp_progress_file_path()
        error_filepath = get_error_file_path()

        # By default we are not resuming and starting from beginning
        progress_json = {"current_id": 0, "export_filepath": output_filepath}

        if should_resume:
            progress_json = read_progress_filepath(
                temp_progress_filepath, output_filepath
            )
            output_filepath = progress_json["export_filepath"]
            print("Resuming from ID", progress_json["current_id"])

        actions_queryset = Action.objects.all()
        claim_queryset = AuthorClaimCase.objects.filter(status="APPROVED")
        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            actions_queryset = actions_queryset.filter(created_date__gte=start_date)

        actions_queryset = (
            actions_queryset.filter(is_removed=False, user__isnull=False)
            .select_related(
                "content_type",
                "user",
            )
            .prefetch_related(
                "item",
                "hubs",
                "user__author_profile",
            )
        )

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            actions_queryset = actions_queryset.filter(created_date__gte=start_date)

        print(f"Number of documents >= {start_date_str}: " + str(len(actions_queryset)))
        print(
            f"Number of approved claims >= {start_date_str}: "
            + str(len(claim_queryset))
        )
        print("*********************************************************************")

        # Actions export
        export_data_to_csv_in_chunks(
            queryset=actions_queryset,
            chunk_processor=map_action_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=output_filepath,
            temp_progress_filepath=temp_progress_filepath,
            last_id=progress_json["current_id"],
            on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
        )

        # Author claim is not captured in Action table. Needs to export separately
        export_data_to_csv_in_chunks(
            queryset=claim_queryset,
            chunk_processor=map_claim_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=output_filepath,
            last_id=0,
            temp_progress_filepath=None,
            on_error=None,
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(temp_progress_filepath)
