from django.core.management.base import BaseCommand

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
            self.style.SUCCESS(f"Done. Total processed: {total_processed}")
        )

    def _process_index(self, index_name, dry_run, batch_size):
        config = INDEX_CONFIGS[index_name]
        qs = config["queryset"]()
        count = qs.count()

        self.stdout.write(f"{config['label']} marked as removed: {count}")

        if dry_run or count == 0:
            return 0

        doc = config["document"]()
        return self._bulk_remove_from_index(doc, qs, count, batch_size, index_name)

    def _bulk_remove_from_index(self, doc, queryset, total, batch_size, label):
        """
        Feeds removed objects through the document update pipeline.
        BaseDocument._get_actions converts these into delete actions
        because should_index_object returns False for removed objects.
        """
        processed = 0
        errors = 0
        last_pk = 0

        while processed < total:
            batch = list(
                queryset.filter(pk__gt=last_pk).order_by("pk")[:batch_size]
            )
            if not batch:
                break

            try:
                doc.update(batch, action="index", raise_on_error=False)
                processed += len(batch)
            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"Error in {label} batch after pk={last_pk}: {e}")
                )
                processed += len(batch)

            last_pk = batch[-1].pk

            if processed % 1000 == 0:
                self.stdout.write(f"  {label}: {processed}/{total}")

        self.stdout.write(
            self.style.SUCCESS(
                f"  {label}: removed {processed} from index"
                + (f" ({errors} batch errors)" if errors else "")
            )
        )
        return processed
