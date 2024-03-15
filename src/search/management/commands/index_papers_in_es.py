from django.core.management.base import BaseCommand
from django.db.models import Q
from elasticsearch.helpers import bulk
from elasticsearch_dsl.connections import connections

from paper.models import Paper
from search.documents.paper import PaperDocument


def index_papers_in_bulk(es, from_id, to_id):
    batch_size = 1000
    current_id = from_id or 1
    to_id = to_id or Paper.objects.all().order_by("-id").first().id
    while True:
        if current_id > to_id:
            break

        print("processing chunk starting with ", current_id)

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
                    "title_suggest": doc.prepare_title_suggest(paper),
                    "updated_date": paper.updated_date or None,
                    "is_open_access": paper.is_open_access or None,
                    "oa_status": paper.oa_status,
                    "pdf_license": paper.pdf_license,
                    "external_source": paper.external_source,
                }

                action = {
                    "_op_type": "index",  # specify the action type here
                    "_index": doc._index._name,  # the index name
                    "_id": paper.id,  # document ID
                    "_source": doc_data,  # the document source
                }

                actions.append(action)

            except:
                print(f"Error processing paper {paper.id}")
                pass

        # Update cursor
        current_id += batch_size

        success, _ = bulk(es, actions)
        print(f"Successfully indexed {success} papers.")


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
