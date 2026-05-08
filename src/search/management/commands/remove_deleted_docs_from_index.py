from django.core.management.base import BaseCommand
from opensearchpy import NotFoundError

from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
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
        "queryset": lambda: Hub.objects.filter(is_removed=True)
        .exclude(namespace="journal")
        .only("id"),
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

    def add_arguments(self, parser):
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
            help="Only process a specific index. If omitted, all indices are processed.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of documents to process per bulk request (default: 500).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        indices = [options["index"]] if options["index"] else INDEX_CONFIGS.keys()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        total_processed = 0
        for index_name in indices:
            total_processed += self._process_index(index_name, dry_run, batch_size)

        self.stdout.write(
            self.style.SUCCESS(f"Done. Total removed from index: {total_processed}")
        )

    def _process_index(self, index_name, dry_run, batch_size):
        config = INDEX_CONFIGS[index_name]
        doc = config["document"]()
        qs = config["queryset"]()
        label = config["label"]

        removed_ids = list(qs.values_list("id", flat=True))
        if not removed_ids:
            self.stdout.write(f"{label}: 0 in database, 0 still in index")
            return 0

        ids_still_in_index = self._find_ids_in_index(doc, removed_ids, batch_size)

        self.stdout.write(
            f"{label}: {len(removed_ids)} removed in database, "
            f"{len(ids_still_in_index)} still in index"
        )

        if not ids_still_in_index:
            return 0

        if dry_run:
            return 0

        return self._bulk_remove_from_index(
            doc, qs, ids_still_in_index, batch_size, label
        )

    def _find_ids_in_index(self, doc, ids, batch_size):
        """Check which of the given IDs still exist in the OpenSearch index."""
        index_name = doc._index._name
        client = doc._get_connection()
        found_ids = []

        for batch_start in range(0, len(ids), batch_size):
            batch_ids = ids[batch_start : batch_start + batch_size]
            try:
                response = client.mget(
                    index=index_name,
                    body={"ids": [str(pk) for pk in batch_ids]},
                )
                for result in response.get("docs", []):
                    if result.get("found"):
                        found_ids.append(int(result["_id"]))
            except NotFoundError:
                continue
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(
                        f"Error checking index {index_name} "
                        f"at offset {batch_start}: {e}"
                    )
                )

        return found_ids

    def _bulk_remove_from_index(self, doc, queryset, ids_to_remove, batch_size, label):
        """
        Feeds removed objects through the document update pipeline.
        BaseDocument._get_actions converts these into delete actions
        because should_index_object returns False for removed objects.
        """
        total = len(ids_to_remove)
        processed = 0
        errors = 0

        for batch_start in range(0, total, batch_size):
            batch_ids = ids_to_remove[batch_start : batch_start + batch_size]
            batch = list(queryset.filter(pk__in=batch_ids))
            if not batch:
                break

            try:
                doc.update(batch, action="index", raise_on_error=False)
                processed += len(batch)
            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Error in {label} batch at offset {batch_start}: {e}"
                    )
                )
                processed += len(batch)

            if processed % 1000 == 0 and processed > 0:
                self.stdout.write(f"  {label}: {processed}/{total}")

        self.stdout.write(
            self.style.SUCCESS(
                f"  {label}: removed {processed} from index"
                + (f" ({errors} batch errors)" if errors else "")
            )
        )
        return processed
