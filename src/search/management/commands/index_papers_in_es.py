import sys
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
        # Flush output. Useful for debugging. Without this command, running script as nohup will not immediately show output.
        sys.stdout.flush()
        print(f"processing chunk starting with: {current_id} ")

        # Get next "chunk"
        chunk_end_id = (
            to_id
            if to_id < current_id + batch_size - 1
            else current_id + batch_size - 1
        )
        queryset = Paper.objects.filter(id__gte=current_id, id__lte=chunk_end_id)

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
                    "abstract": paper.abstract or "",
                    "authors": paper.authors or [],
                    "can_display_pdf_license": doc.prepare_can_display_pdf_license(
                        paper
                    )
                    or False,
                    "citation_percentile": paper.citation_percentile or 0,
                    "citations": paper.citations or 0,
                    "completeness_status": paper.get_paper_completeness(),
                    "discussion_count": paper.discussion_count or 0,
                    "doi": paper.doi or None,
                    "external_source": paper.external_source,
                    "hot_score": doc.prepare_hot_score(paper),
                    "hubs_flat": paper.hubs_indexing_flat or None,
                    "hubs": paper.hubs_indexing or [],
                    "id": paper.id,
                    "oa_status": paper.oa_status,
                    "openalex_id": paper.openalex_id,
                    "paper_publish_date": paper.paper_publish_date or None,
                    "paper_publish_year": doc.prepare_paper_publish_year(paper),
                    "paper_title": paper.paper_title or "",
                    "pdf_license": paper.pdf_license,
                    "raw_authors": paper.raw_authors_indexing or [],
                    "slug": paper.slug or None,
                    "suggestion_phrases": doc.prepare_suggestion_phrases(paper),
                    "title": paper.title or None,
                    "updated_date": paper.updated_date or None,
                }

                action = {
                    "_op_type": "index",
                    "_index": doc._index._name,
                    "_id": paper.id,
                    "_source": doc_data,
                }

                actions.append(action)

            except Exception as e:
                print(f"Error processing paper {paper.id}: {e}")
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
                        f"Failed to index papers after {max_attempts} attempts due to persistent timeouts. Last ID attempted was {current_id}: {e}"
                    )
                    return
                else:
                    wait_time = 2**attempt  # Exponential backoff
                    print(
                        f"Timeout encountered: {e}. Retrying batch starting at {current_id} in {wait_time} seconds (Attempt {attempt}/{max_attempts})..."
                    )
                    time.sleep(wait_time)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--start-id", type=int, help="ID to start indexing from", default=1
        )
        parser.add_argument(
            "--end-id", type=int, help="ID to stop indexing at", default=None
        )

    help = "Bulk index papers in Elasticsearch"

    def handle(self, *args, **options):
        start_id = options["start_id"]
        end_id = options["end_id"]
        es = connections.get_connection()
        index_papers_in_bulk(es, start_id, end_id)
