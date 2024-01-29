import csv
import json
import os
import time
from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_mapping_utils import build_doc_props_for_item
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument

CHUNK_SIZE = 2
OUTPUT_FILE = "./exported_items.csv"
TEMP_PROGRESS_FILE = "./item-export-progress.temp.json"
EXPORT_FILE_HEADERS = [
    "ITEM_ID",
    "CREATION_TIMESTAMP",
    "item_type",
    "item_subtype",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "bounty_id",
    "bounty_amount",
    "bounty_type",
    "bounty_expiration_timestamp",
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
    "hubs",
    "hub_slugs",
    "primary_hub",
]
MODELS_TO_EXPORT = [
    "ResearchhubUnifiedDocument",
    "RhCommentModel",
]


def export_data_to_csv_in_chunks(
    queryset,
    current_model_to_export,
    all_models_to_export,
    chunk_processor,
    headers,
    output_filepath,
    temp_progress_filepath,
    last_id=0,
):
    _last_id = last_id
    chunk_num = 1

    while True:
        _queryset = queryset.filter(id__gt=_last_id).order_by("id")[:CHUNK_SIZE]
        chunk = list(_queryset.iterator())

        if not chunk:
            break

        # Process the chunk with the provided function
        processed_chunk = chunk_processor(chunk)

        write_data_to_csv(processed_chunk, headers, output_filepath)

        print(f"Successfully exported chunk {chunk_num} {output_filepath}")

        # Move the pointers forward
        last_record = chunk[-1]
        _last_id = last_record.id
        chunk_num += 1
        # Write progress to temp file in case something goes wrong
        write_last_processed_id(
            current_model_to_export,
            all_models_to_export,
            _last_id,
            temp_progress_filepath,
        )

        # raise Exception("stop")


def read_last_processed_ids(filepath, models_to_export):
    if os.path.exists(filepath):
        with open(filepath, "r") as file:
            return json.load(file)

    return {key: 0 for key in models_to_export}


def write_last_processed_id(model_name, models_to_export, last_id, filepath):
    ids = read_last_processed_ids(filepath, models_to_export)
    ids[model_name] = last_id
    with open(filepath, "w") as file:
        json.dump(ids, file)


def remove_file(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"file '{filepath}' has been removed.")
    except Exception as e:
        print(f"Error occurred while removing the file: {e}")


def map_document_data(docs):
    data = []
    for doc in docs:
        try:
            record = {}
            item_type = doc.get_client_doc_type()
            specific_doc = doc.get_document()  # paper, post, ...

            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = item_type + "_" + str(specific_doc.id)
            record["item_type"] = item_type
            record["internal_item_id"] = str(specific_doc.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(doc.created_date.timetuple())
            )
            record["updated_timestamp"] = int(time.mktime(doc.updated_date.timetuple()))

            if specific_doc.created_by:
                record["created_by_user_id"] = str(specific_doc.created_by.id)

            data.append(record)
        except Exception as e:
            print("Failed to export doc: " + str(doc.id), e)

    return data


def map_comment_data(comments):
    data = []

    # Comments, Peer Reviews, ..
    for comment in comments:
        try:
            record = {}
            if comment.unified_document:
                doc_props = build_doc_props_for_item(comment.unified_document)
                record = {**doc_props}

            record["ITEM_ID"] = "comment" + "_" + str(comment.id)
            record["item_type"] = "comment"
            record["item_subtype"] = comment.comment_type
            record["internal_item_id"] = str(comment.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(comment.created_date.timetuple())
            )
            record["created_by_user_id"] = str(comment.created_by.id)

            bounties = comment.bounties.filter(status="OPEN").order_by("-amount")
            if bounties.exists():
                bounty = bounties.first()
                record["bounty_amount"] = bounty.amount
                record["bounty_id"] = "bounty_" + str(bounty.id)
                record["bounty_type"] = bounty.bounty_type
                record["bounty_expiration_timestamp"] = int(
                    time.mktime(bounty.created_date.timetuple())
                )

            data.append(record)
        except Exception as e:
            print("Failed to export comment:" + str(comment.id), e)

    return data


def write_data_to_csv(data, headers, output_filepath):
    # Check if the file already exists to determine whether to write headers
    file_exists = os.path.isfile(output_filepath)

    # Open the file in append mode instead of write mode
    with open(output_filepath, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=headers)

        # Write the header only if the file didn't exist
        if not file_exists:
            writer.writeheader()

        # Write the data
        for item in data:
            writer.writerow(item)


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

        docs_queryset = ResearchhubUnifiedDocument.objects.filter(
            document_type__in=["PAPER", "DISCUSSION", "QUESTION", "PREREGISTRATION"],
            is_removed=False,
        )
        comments_queryset = RhCommentModel.objects.filter(is_removed=False)

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            docs_queryset = docs_queryset.filter(created_date__gte=start_date)
            comments_queryset = comments_queryset.filter(created_date__gte=start_date)

        print(f"Number of documents >= {start_date_str}: " + str(len(docs_queryset)))
        print(f"Number of comments >= {start_date_str}: " + str(len(comments_queryset)))
        print("*********************************************************************")

        export_data_to_csv_in_chunks(
            queryset=docs_queryset,
            current_model_to_export="ResearchhubUnifiedDocument",
            all_models_to_export=MODELS_TO_EXPORT,
            chunk_processor=map_document_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=OUTPUT_FILE,
            temp_progress_filepath=TEMP_PROGRESS_FILE,
            last_id=last_completed_ids["ResearchhubUnifiedDocument"],
        )
        export_data_to_csv_in_chunks(
            queryset=comments_queryset,
            current_model_to_export="RhCommentModel",
            all_models_to_export=MODELS_TO_EXPORT,
            chunk_processor=map_comment_data,
            headers=EXPORT_FILE_HEADERS,
            output_filepath=OUTPUT_FILE,
            temp_progress_filepath=TEMP_PROGRESS_FILE,
            last_id=last_completed_ids["RhCommentModel"],
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(TEMP_PROGRESS_FILE)
