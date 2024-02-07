import os
import time
from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.utils.analytics_file_utils import (
    export_data_to_csv_in_chunks,
    read_last_processed_ids,
    remove_file,
)
from analytics.utils.analytics_mapping_utils import (
    build_doc_props_for_item,
    get_open_bounty_count,
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

EXPORT_FILE_HEADERS = [
    "ITEM_ID",
    "CREATION_TIMESTAMP",
    "item_type",
    "item_subtype",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "discussion_count",
    "hot_score",
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
]

MODELS_TO_EXPORT = [
    "ResearchhubUnifiedDocument",
    "RhCommentModel",
    "Bounty",
]


def map_paper_data(docs):
    from paper.related_models.paper_model import Paper

    data = []
    for doc in docs:
        try:
            paper = doc.get_document()
            # The following clause aims to prevent papers with missing criticial or interesting data (e.g. comments)
            # from being recommneded by Amazon personalize
            completeness = paper.get_paper_completeness()
            if completeness == Paper.PARTIAL:
                if paper.discussion_count == 0:
                    print(
                        "skipping partially completed paper: ",
                        paper.title,
                        paper.id,
                    )
                    continue
            elif completeness == Paper.INCOMPLETE:
                print("skipping incomplete paper: ", paper.title, paper.id)
                continue

            record = {}
            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = paper.get_analytics_id()
            record["internal_item_id"] = str(paper.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(doc.created_date.timetuple())
            )
            record["updated_timestamp"] = int(time.mktime(doc.updated_date.timetuple()))
            record["open_bounty_count"] = get_open_bounty_count(doc)

            if paper.created_by:
                record["created_by_user_id"] = str(paper.created_by.id)

            data.append(record)
        except Exception as e:
            print("Failed to export doc: " + str(doc.id), e)

    return data


def map_document_data(docs):
    from paper.related_models.paper_model import Paper

    data = []
    for doc in docs:
        try:
            # The following clause aims to prevent papers with missing criticial or interesting data (e.g. comments)
            # from being recommneded by Amazon personalize
            if doc.document_type == "PAPER":
                paper = doc.paper
                completeness = paper.get_paper_completeness()
                if completeness == Paper.PARTIAL:
                    if paper.discussion_count == 0:
                        print(
                            "skipping partially completed paper: ",
                            paper.title,
                            paper.id,
                        )
                        continue
                elif completeness == Paper.INCOMPLETE:
                    print("skipping incomplete paper: ", paper.title, paper.id)
                    continue

            record = {}
            specific_doc = doc.get_document()  # paper, post, ...

            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = specific_doc.get_analytics_id()
            record["item_type"] = specific_doc.get_analytics_type()
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

            record["ITEM_ID"] = comment.get_analytics_id()
            record["item_type"] = comment.get_analytics_type()
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
                record["bounty_id"] = bounty.get_analytics_id()
                record["bounty_type"] = bounty.get_analytics_type()
                record["bounty_expiration_timestamp"] = int(
                    time.mktime(bounty.created_date.timetuple())
                )

            data.append(record)
        except Exception as e:
            print("Failed to export comment:" + str(comment.id), e)

    return data


EXPORT_ITEM_HELPER = {
    "paper": {
        "model": "ResearchhubUnifiedDocument",
        "mapper": map_paper_data,
        "headers": PAPER_HEADERS,
    },
    "post": "ResearchhubUnifiedDocument",
    "comment": "RhCommentModel",
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
        elif export_type == "preregistration":
            queryset = ResearchhubUnifiedDocument.objects.filter(
                document_type__in=["PREREGISTRATION"],
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
            last_id=last_completed_ids["ResearchhubUnifiedDocument"],
        )

        # Cleanup the temp file pointing to our export progress thus far
        remove_file(TEMP_PROGRESS_FILE)
