from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Q

from analytics.utils.analytics_file_utils import (
    write_data_to_csv,
    write_to_progress_filepath,
)
from analytics.utils.analytics_mappers import map_paper_data, map_post_data
from researchhub_document.related_models.constants.document_type import (
    ELN,
    HYPOTHESIS,
    NOTE,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


def get_temp_progress_file_path(item_type: str, output_path: str):
    return f"{output_path}/{item_type}-item-export-progress.temp.json"


def get_output_file_path(item_type: str, output_path: str):
    now = datetime.now()
    date_string = now.strftime("%m_%d_%y_%H_%M_%S")
    return f"{output_path}/{item_type}-item-export-{date_string}.csv"


def get_error_file_path(item_type: str, output_path: str):
    return f"{output_path}/{item_type}-item-export-errors.txt"


def write_error_to_file(id, error, error_filepath):
    with open(error_filepath, "a") as file:
        file.write(f"ID: {id}, ERROR: {error}\n")


HEADERS = [
    "ITEM_ID",
    "item_type",
    "CREATION_TIMESTAMP",
    "internal_item_id",
    "unified_document_id",
    "created_by_user_id",
    "discussion_count",
    "hot_score",
    "open_bounty_count",
    "bounty_type",
    "bounty_status",
    "bounty_parent_id",
    "bounty_expiration_timestamp",
    "bounty_is_expiring_soon",
    "bounty_has_solution",
    "body",
    "peer_review_score",
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


def export_posts(from_id, to_id=None, size=1000, process_chunk: callable = None):
    from researchhub_document.related_models.researchhub_post_model import (
        ResearchhubPost,
    )

    current_id = from_id
    while True:
        if to_id and current_id > to_id:
            break

        posts = ResearchhubPost.objects.filter(
            id__gte=from_id, id__lte=(from_id + size - 1)
        ).exclude(
            document_type__in=[HYPOTHESIS, ELN, NOTE],
        )

        related_unidoc_ids = posts.values_list("unified_document_id", flat=True)
        queryset = ResearchhubUnifiedDocument.objects.filter(
            id__in=related_unidoc_ids, is_removed=False
        )

        # Keep going until no more!
        if queryset.exists() is False:
            break

        print(
            "processing posts from: ",
            from_id,
            " to: ",
            from_id + size - 1,
            " eligible results: ",
            queryset.count(),
        )

        if process_chunk:
            process_chunk(queryset)

        # Update cursor
        from_id += size


def export_papers(from_id, to_id=None, size=1000, process_chunk: callable = None):
    from paper.related_models.paper_model import Paper

    current_id = from_id
    while True:
        if to_id and current_id > to_id:
            break

        # Get next "chunk"
        queryset = Paper.objects.filter(id__gte=from_id, id__lte=(from_id + size - 1))

        # Keep going until no more!
        if queryset.exists() is False:
            break

        # The following is meant to filter out papers that are not "COMPLETE"
        queryset = (
            queryset.exclude(
                Q(unified_document_id__isnull=True)
                | Q(abstract__isnull=True)
                | Q(title__isnull=True)
                | Q(is_removed=True)
                | Q(doi__isnull=True)
                | Q(open_alex_raw_json__isnull=True)
                | Q(oa_status="closed")
            )
            .exclude(
                pdf_url__isnull=True,
                file__isnull=True,
            )
            .filter(unified_document__hubs__isnull=False)
            .distinct()
        )

        print(
            "processing papers from: ",
            from_id,
            " to: ",
            from_id + size - 1,
            " eligible results: ",
            queryset.count(),
        )

        if process_chunk:
            process_chunk(queryset)

        # Update cursor
        from_id += size


class Command(BaseCommand):
    help = "Export item data to personalize"

    def add_arguments(self, parser):
        parser.add_argument(
            "--type", type=str, help="The type you would like to export"
        )
        parser.add_argument("--output_path", type=str, help="The output path")
        parser.add_argument("--from_id", type=str, help="start at a particular id")

    def handle(self, *args, **kwargs):
        from_id = kwargs["from_id"] or 1
        output_path = kwargs["output_path"]
        export_type = kwargs["type"]

        # Related files
        output_filepath = get_output_file_path(export_type, output_path)
        temp_progress_filepath = get_temp_progress_file_path(export_type, output_path)
        error_filepath = get_error_file_path(export_type, output_path)

        if export_type == "paper" or export_type == "all":

            def process_paper_item_chunk(queryset, headers):
                mapped_results = map_paper_data(
                    queryset,
                    on_error=lambda id, msg: write_error_to_file(
                        id, msg, error_filepath
                    ),
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

            export_papers(
                from_id=from_id,
                process_chunk=lambda queryset: process_paper_item_chunk(
                    queryset, HEADERS
                ),
            )

        if export_type == "post" or export_type == "all":

            def process_post_item_chunk(queryset, headers):
                mapped_results = map_post_data(
                    queryset,
                    on_error=lambda id, msg: write_error_to_file(
                        id, msg, error_filepath
                    ),
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

            export_posts(
                from_id=from_id,
                process_chunk=lambda queryset: process_post_item_chunk(
                    queryset, HEADERS
                ),
            )
