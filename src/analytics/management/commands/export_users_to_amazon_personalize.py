from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_progress_filepath,
    remove_file,
)
from analytics.utils.analytics_mappers import map_user_data
from analytics.utils.analytics_mapping_utils import build_hub_str
from user.related_models.user_model import User

OUTPUT_FILE = "./exported_user_data.csv"
TEMP_PROGRESS_FILE = "./user-export-progress.temp.json"
EXPORT_FILE_HEADERS = [
    "USER_ID",
    "interest_hubs",
    "expertise_hubs",
]


def get_output_file_path(output_path: str):
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"./user-export-{date_string}.csv"


def get_error_file_path(output_path: str):
    return f"./user-export-errors.txt"


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
        parser.add_argument("--output_path", type=str, help="The output path")

    def handle(self, *args, **kwargs):
        start_date_str = kwargs["start_date"]
        should_resume = kwargs["resume"]
        output_path = kwargs["output_path"]

        # Related files
        output_filepath = get_output_file_path(output_path)
        error_filepath = get_error_file_path(output_path)

        # By default we are not resuming and starting from beginning
        progress_json = {"current_id": 0, "export_filepath": output_filepath}

        if should_resume:
            progress_json = read_progress_filepath(TEMP_PROGRESS_FILE, output_filepath)
            output_filepath = progress_json["export_filepath"]
            print("Resuming from ID", progress_json["current_id"])

        queryset = User.objects.all()
        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            queryset = queryset.filter(created_date__gte=start_date)

        queryset = queryset.prefetch_related(
            "author_profile",
        )

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            queryset = queryset.filter(created_date__gte=start_date)

        print(f"Number of users >= {start_date_str}: " + str(len(queryset)))
        print("*********************************************************************")

        export_data_to_csv_in_chunks(
            queryset=queryset,
            chunk_processor=map_user_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=OUTPUT_FILE,
            last_id=progress_json["current_id"],
            temp_progress_filepath=TEMP_PROGRESS_FILE,
            on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(TEMP_PROGRESS_FILE)
