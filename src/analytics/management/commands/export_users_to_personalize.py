import os
from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_last_processed_ids,
    remove_file,
)
from analytics.utils.analytics_mapping_utils import build_hub_str
from user.related_models.user_model import User

OUTPUT_FILE = "./exported_user_data.csv"
TEMP_PROGRESS_FILE = "./user-export-progress.temp.json"
EXPORT_FILE_HEADERS = [
    "USER_ID",
    "interest_hubs",
    "expertise_hubs",
]
MODELS_TO_EXPORT = ["User"]


def map_user_data(queryset):
    data = []
    for user in queryset:
        try:
            record = {}
            interests = user.author_profile.get_interest_hubs()
            expertise = user.author_profile.get_expertise_hubs()

            record["USER_ID"] = str(user.id)
            record["interest_hubs"] = "|".join(
                [build_hub_str(hub) for hub in interests]
            )
            record["expertise_hubs"] = "|".join(
                [build_hub_str(hub) for hub in expertise]
            )
            data.append(record)

        except Exception as e:
            print("Failed to export user: " + str(user.id), e)

    return data


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
        force = kwargs["force"]

        # Check if the file already so we don't accidentally override it and cry over time lost :(
        file_exists = os.path.isfile(OUTPUT_FILE)
        if file_exists and not should_resume:
            if force:
                remove_file(OUTPUT_FILE)
            else:
                print(
                    f"File {OUTPUT_FILE} already exists. Please delete it or use --force to override it."
                )
                return

        # By default we are not resuming and starting from 0
        last_completed_ids = {key: 0 for key in MODELS_TO_EXPORT}

        if should_resume:
            last_completed_ids = read_last_processed_ids(
                TEMP_PROGRESS_FILE, MODELS_TO_EXPORT
            )
            print("Resuming", last_completed_ids)

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
            current_model_to_export="User",
            all_models_to_export=MODELS_TO_EXPORT,
            chunk_processor=map_user_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=OUTPUT_FILE,
            temp_progress_filepath=TEMP_PROGRESS_FILE,
            last_id=last_completed_ids["User"],
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(TEMP_PROGRESS_FILE)
