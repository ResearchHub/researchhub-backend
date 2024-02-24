from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    write_data_to_csv,
    write_to_progress_filepath,
)
from analytics.utils.analytics_mappers import map_user_data
from user.related_models.user_model import User

TEMP_PROGRESS_FILE = "./user-export-progress.temp.json"
HEADERS = [
    "USER_ID",
    "user_interest_hub_ids",
    "user_expertise_hub_ids",
]


def get_output_file_path(output_path: str):
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"{output_path}/user-export-{date_string}.csv"


def get_temp_progress_file_path(output_path: str):
    return f"{output_path}/user-export-progress.temp.json"


def get_error_file_path(output_path: str):
    return f"{output_path}/user-export-errors.txt"


def write_error_to_file(id, error, error_filepath):
    with open(error_filepath, "a") as file:
        file.write(f"ID: {id}, ERROR: {error}\n")


def export_users(from_id, to_id=None, size=1000, process_chunk: callable = None):
    current_id = from_id
    to_id = to_id or User.objects.all().order_by("-id").first().id
    while True:
        if current_id > to_id:
            break

        # Get next "chunk"
        queryset = User.objects.filter(
            id__gte=current_id, id__lte=(current_id + size - 1)
        )

        print(
            "processing users from: ",
            from_id,
            " to: ",
            from_id + size - 1,
            " eligible results: ",
            queryset.count(),
        )

        if process_chunk:
            process_chunk(queryset)

        # Update cursor
        current_id += size


class Command(BaseCommand):
    help = "Export users data to personalize"

    def add_arguments(self, parser):
        parser.add_argument("--output_path", type=str, help="The output path")
        parser.add_argument("--from_id", type=str, help="start at a particular id")

    def handle(self, *args, **kwargs):
        from_id = int(kwargs["from_id"] or 1)
        output_path = kwargs["output_path"]

        # Related files
        output_filepath = get_output_file_path(output_path)
        temp_progress_filepath = get_temp_progress_file_path(output_path)
        error_filepath = get_error_file_path(output_path)

        def process_user_chunk(queryset, headers):
            mapped_results = map_user_data(
                queryset,
                on_error=lambda id, msg: write_error_to_file(id, msg, error_filepath),
            )

            write_data_to_csv(
                data=mapped_results,
                headers=headers,
                output_filepath=output_filepath,
            )

            # Write progress to temp file in case something goes wrong
            if temp_progress_filepath:
                last_item = queryset.last()

                if last_item:
                    write_to_progress_filepath(
                        last_id=last_item.id,
                        progress_filepath=temp_progress_filepath,
                        export_filepath=output_filepath,
                    )

        export_users(
            from_id=from_id,
            process_chunk=lambda queryset: process_user_chunk(queryset, HEADERS),
        )

        print("Export complete", output_filepath)
