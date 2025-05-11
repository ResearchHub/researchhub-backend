from django.core.management.base import BaseCommand

from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubUnifiedDocument


class Command(BaseCommand):
    help = "Recompute and persist accurate discussion_count values."

    def add_arguments(self, parser):
        parser.add_argument(
            "--doc-id",
            type=int,
            help="UnifiedDocument id to refresh (refreshes all when omitted)",
        )

    def handle(self, *args, **options):
        doc_id = options.get("doc_id")
        if doc_id:
            self.stdout.write(f"Refreshing discussion_count for doc {doc_id}…")
        else:
            self.stdout.write("Refreshing discussion_count for ALL documents…")

        if doc_id is not None:
            try:
                ud = ResearchhubUnifiedDocument.objects.get(id=doc_id)
            except ResearchhubUnifiedDocument.DoesNotExist:
                self.stderr.write(self.style.ERROR("UnifiedDocument not found"))
                return
            concrete = ud.get_document()
            if not hasattr(concrete, "rh_threads"):
                self.stderr.write("Document has no rh_threads relation; skipping")
                return
            thread_ids = concrete.rh_threads.values_list("id", flat=True)
            comments_qs = RhCommentModel.objects.filter(thread_id__in=thread_ids)
        else:
            # Any comment implies its document needs refresh; iterate through comments.
            comments_qs = RhCommentModel.objects.all()

        processed = set()
        for comment in comments_qs.iterator():
            ud = comment.unified_document
            if ud and ud.id not in processed:
                comment.refresh_related_discussion_count()
                processed.add(ud.id)
                self.stdout.write(
                    f"Updated doc {ud.id} -> {ud.get_document().discussion_count}"
                )

        self.stdout.write(
            self.style.SUCCESS(f"Done. Updated {len(processed)} documents.")
        )
