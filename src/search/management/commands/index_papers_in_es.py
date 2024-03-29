import time

import elasticsearch
from django.core.management.base import BaseCommand
from django.db.models import Q
from elasticsearch.helpers import bulk
from elasticsearch_dsl.connections import connections

from paper.models import Paper
from search.documents.paper import PaperDocument


def index_papers_in_bulk(es, from_id, to_id, max_attempts=5):
    batch_size = 2500
    current_id = from_id or 1
    to_id = to_id or Paper.objects.all().order_by("-id").first().id

    while current_id <= to_id:
        print(f"processing chunk starting with: {current_id} ")

        # Get next "chunk"
        queryset = Paper.objects.filter(
            id__gte=current_id, id__lte=(current_id + batch_size - 1)
        )

        queryset = (
            queryset.exclude(Q(title__isnull=True) | Q(is_removed=True))
            .distinct()
            .order_by("id")
        )

        actions = []
        for paper in queryset:
            try:
                # We would typically not need to create a new instance of a document
                # and assign data to it, but it is necessary here because we are bypassing
                # the normal indexing process which normally happens via rebuild_index command.
                # NOTE: Any attribute we would need to index will have to be assigned here.
                doc = PaperDocument()
                doc.meta.id = paper.id
                doc_data = {
                    "id": paper.id,
                    "hubs_flat": paper.hubs_indexing_flat or None,
                    "paper_title": paper.paper_title or "",
                    "paper_publish_date": paper.paper_publish_date or None,
                    "abstract": paper.abstract or "",
                    "doi": paper.doi or None,
                    "raw_authors": paper.raw_authors_indexing or [],
                    "hubs": paper.hubs_indexing or [],
                    "slug": paper.slug or None,
                    "title": paper.title or None,
                    "suggestion_phrases": doc.prepare_suggestion_phrases(paper),
                    "updated_date": paper.updated_date or None,
                    "is_open_access": paper.is_open_access or None,
                    "oa_status": paper.oa_status,
                    "pdf_license": paper.pdf_license,
                    "external_source": paper.external_source,
                }

                action = {
                    "_op_type": "index",
                    "_index": doc._index._name,
                    "_id": paper.id,
                    "_source": doc_data,
                }

                actions.append(action)

            except:
                print(f"Error processing paper {paper.id}")
                pass

        for attempt in range(1, max_attempts + 1):
            try:
                success, _ = bulk(es, actions, request_timeout=120)
                print(
                    f"Successfully indexed {success} papers from starting ID {current_id}."
                )
                current_id += batch_size
                break  # Break out of the retry loop on success
            except (
                elasticsearch.exceptions.TransportError,
                elasticsearch.exceptions.ConnectionTimeout,
            ) as e:
                if attempt == max_attempts:
                    print(
                        f"Failed to index papers after {max_attempts} attempts due to persistent timeouts. Last ID attempted was {current_id}."
                    )
                    return
                else:
                    wait_time = 2**attempt  # Exponential backoff
                    print(
                        f"Timeout encountered. Retrying batch starting at {current_id} in {wait_time} seconds (Attempt {attempt}/{max_attempts})..."
                    )
                    time.sleep(wait_time)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--start-id", type=int, help="ID to start indexing from", default=1
        )

    help = "Bulk index papers in Elasticsearch"

    def handle(self, *args, **options):
        start_id = options["start_id"]
        es = connections.get_connection()
        index_papers_in_bulk(es, start_id, None)
