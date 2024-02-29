from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    write_data_to_csv,
    write_to_progress_filepath,
)
from analytics.utils.analytics_mappers import map_action_data, map_claim_data
from researchhub_case.related_models.author_claim_case_model import AuthorClaimCase
from user.models import Action

HEADERS = [
    "ITEM_ID",
    "EVENT_TYPE",
    "TIMESTAMP",
    "EVENT_VALUE",
    "USER_ID",
    "hub_ids",
]


def get_temp_progress_file_path(output_path: str):
    return f"{output_path}/interaction-export-progress.temp.json"


def get_output_file_path(output_path: str):
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"{output_path}/interaction-export-{date_string}.csv"


def get_error_file_path(output_path: str):
    return f"{output_path}/interaction-export-errors.txt"


def write_error_to_file(id, error, error_filepath):
    with open(error_filepath, "a") as file:
        file.write(f"ID: {id}, ERROR: {error}\n")


def export_actions(from_id, to_id=None, size=1000, process_chunk: callable = None):
    current_id = from_id
    to_id = to_id or Action.objects.all().order_by("-id").first().id
    while True:
        if current_id > to_id:
            break

        # Get next "chunk"
        queryset = Action.objects.filter(
            id__gte=current_id, id__lte=(current_id + size - 1)
        )

        queryset = (
            queryset.filter(is_removed=False, user__isnull=False)
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

        print(
            "processing actions from: ",
            current_id,
            " to: ",
            current_id + size - 1,
            " eligible results: ",
            queryset.count(),
        )

        if process_chunk:
            process_chunk(queryset)

        # Update cursor
        current_id += size


def export_author_claim_cases(
    from_id, to_id=None, size=1000, process_chunk: callable = None
):
    current_id = from_id
    to_id = to_id or AuthorClaimCase.objects.all().order_by("-id").first().id
    while True:
        if current_id > to_id:
            break

        # Get next "chunk"
        queryset = AuthorClaimCase.objects.filter(
            id__gte=current_id, id__lte=(current_id + size - 1)
        )
        queryset.filter(status="APPROVED")

        print(
            "processing claim from: ",
            current_id,
            " to: ",
            current_id + size - 1,
            " eligible results: ",
            queryset.count(),
        )

        if process_chunk:
            process_chunk(queryset)

        # Update cursor
        current_id += size


class Command(BaseCommand):
    help = "Export interaction data to personalize"

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

        def process_action_chunk(queryset, headers):
            mapped_results = map_action_data(
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

        export_actions(
            from_id=from_id,
            process_chunk=lambda queryset: process_action_chunk(queryset, HEADERS),
        )

        def process_claim_chunk(queryset, headers):
            mapped_results = map_claim_data(
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

        export_author_claim_cases(
            from_id=from_id,
            process_chunk=lambda queryset: process_claim_chunk(queryset, HEADERS),
        )

        print("Export complete!", output_filepath)
