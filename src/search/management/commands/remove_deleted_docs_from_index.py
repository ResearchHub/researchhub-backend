from django.core.management.base import BaseCommand, CommandParser
from django.db.models import QuerySet
from opensearchpy import NotFoundError

from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from search.documents.base import BaseDocument
from search.documents.hub import HubDocument
from search.documents.journal import JournalDocument
from search.documents.paper import PaperDocument
from search.documents.post import PostDocument

INDEX_CONFIGS = {
    "paper": {
        "document": PaperDocument,
        "queryset": lambda: Paper.objects.filter(is_removed=True).only(
            "id", "is_removed"
        ),
        "label": "Papers",
    },
    "post": {
        "document": PostDocument,
        "queryset": lambda: ResearchhubPost.objects.filter(
            unified_document__is_removed=True
        ).only("id"),
        "label": "Posts",
    },
    "hub": {
        "document": HubDocument,
        "queryset": lambda: (
            Hub.objects.filter(is_removed=True).exclude(namespace="journal").only("id")
        ),
        "label": "Hubs",
    },
    "journal": {
        "document": JournalDocument,
        "queryset": lambda: Hub.objects.filter(
            is_removed=True, namespace="journal"
        ).only("id"),
        "label": "Journals",
    },
}


class Command(BaseCommand):
    help = "Remove soft-deleted documents from OpenSearch indices"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only report counts without modifying the index.",
        )
        parser.add_argument(
            "--index",
            type=str,
            choices=INDEX_CONFIGS.keys(),
            default=None,
            help=(
                "Only process a specific index. If omitted, all indices are processed."
            ),
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of documents to process per bulk request (default: 500).",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        batch_size: int = options["batch_size"]
        indices = [options["index"]] if options["index"] else INDEX_CONFIGS.keys()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        total_processed = 0
        for index_name in indices:
            total_processed += self._process_index(index_name, dry_run, batch_size)

        self.stdout.write(
            self.style.SUCCESS(f"Done. Total removed from index: {total_processed}")
        )

    def _process_index(self, index_name: str, dry_run: bool, batch_size: int) -> int:
        config = INDEX_CONFIGS[index_name]
        doc: BaseDocument = config["document"]()
        qs: QuerySet = config["queryset"]()
        label: str = config["label"]
        client = doc._get_connection()
        opensearch_index = doc._index._name

        total_removed = 0
        still_in_index = 0
        processed = 0
        errors = 0
        batch = []

        for obj in qs.iterator(chunk_size=batch_size):
            batch.append(obj)

            if len(batch) < batch_size:
                continue

            total_removed += len(batch)
            found, removed, errs = self._check_and_remove_batch(
                doc, client, opensearch_index, label, batch, dry_run
            )
            still_in_index += found
            processed += removed
            errors += errs
            batch = []

        if batch:
            total_removed += len(batch)
            found, removed, errs = self._check_and_remove_batch(
                doc, client, opensearch_index, label, batch, dry_run
            )
            still_in_index += found
            processed += removed
            errors += errs

        self.stdout.write(
            f"{label}: {total_removed} removed in database, "
            f"{still_in_index} still in index"
        )
        if processed > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {label}: removed {processed} from index"
                    + (f" ({errors} batch errors)" if errors else "")
                )
            )
        return processed

    def _check_and_remove_batch(
        self,
        doc: BaseDocument,
        client,
        opensearch_index: str,
        label: str,
        batch: list,
        dry_run: bool,
    ) -> tuple[int, int, int]:
        """Returns (found_count, removed_count, error_count)."""
        batch_ids = [obj.pk for obj in batch]
        ids_in_index = self._find_ids_in_index(client, opensearch_index, batch_ids)

        if not ids_in_index or dry_run:
            return len(ids_in_index), 0, 0

        ids_set = set(ids_in_index)
        to_remove = [obj for obj in batch if obj.pk in ids_set]
        try:
            doc.update(to_remove, action="index", raise_on_error=False)
            return len(ids_in_index), len(to_remove), 0
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error removing {label} batch: {e}"))
            return len(ids_in_index), len(to_remove), 1

    def _find_ids_in_index(
        self, client, opensearch_index: str, ids: list[int]
    ) -> list[int]:
        """Check which of the given IDs exist in the OpenSearch index."""
        try:
            response = client.mget(
                index=opensearch_index,
                body={"ids": [str(pk) for pk in ids]},
            )
            return [
                int(result["_id"])
                for result in response.get("docs", [])
                if result.get("found")
            ]
        except NotFoundError:
            return []
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Error checking index {opensearch_index}: {e}")
            )
            return []
