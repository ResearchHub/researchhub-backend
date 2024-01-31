import os
from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_last_processed_ids,
    remove_file,
)
from analytics.utils.analytics_mapping_utils import (
    build_bounty_event,
    build_comment_event,
    build_doc_props_for_item,
    build_rsc_spend_event,
    build_vote_event,
)
from discussion.reaction_models import Vote
from user.models import Action

OUTPUT_FILE = "./exported_interaction_data.csv"
TEMP_PROGRESS_FILE = "./interaction-export-progress.temp.json"
EXPORT_FILE_HEADERS = [
    "ITEM_ID",
    "EVENT_TYPE",
    "TIMESTAMP",
    "EVENT_VALUE",
    "USER_ID",
    "related_item_id",
    "internal_item_id",
    "unified_document_id",
    "primary_hub",
]
MODELS_TO_EXPORT = ["Action"]


def map_action_data(actions):
    data = []
    for action in actions:
        try:
            if action.content_type.model == "bounty":
                event = build_bounty_event(action)
                data.append(event)
            elif action.content_type.model == "vote":
                if action.item.vote_type == Vote.DOWNVOTE:
                    # Skip downvotes since they are not beneficial for machine learning models
                    continue

                event = build_vote_event(action)
                data.append(event)
            elif action.content_type.model == "rhcommentmodel":
                event = build_comment_event(action)
                data.append(event)
            elif action.content_type.model == "purchase":
                event = build_rsc_spend_event(action)
                data.append(event)
        except Exception as e:
            print("Failed to export action: " + str(action.id), e)

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

        actions_queryset = Action.objects.all()
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
        print("*********************************************************************")

        export_data_to_csv_in_chunks(
            queryset=actions_queryset,
            current_model_to_export="Action",
            all_models_to_export=MODELS_TO_EXPORT,
            chunk_processor=map_action_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=OUTPUT_FILE,
            temp_progress_filepath=TEMP_PROGRESS_FILE,
            last_id=last_completed_ids["Action"],
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(TEMP_PROGRESS_FILE)
