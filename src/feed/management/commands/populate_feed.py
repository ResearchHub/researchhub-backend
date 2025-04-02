import logging

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from feed.models import FeedEntry
from feed.serializers import serialize_feed_item, serialize_feed_metrics
from paper.models import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Populates feed entries for all existing comments and papers "
        "with a unified document with hubs"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for processing items",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Don't actually create feed entries, just print what would happen",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recreating feed entries even if they already exist",
        )
        parser.add_argument(
            "--papers-only",
            action="store_true",
            help="Only process papers",
        )
        parser.add_argument(
            "--comments-only",
            action="store_true",
            help="Only process comments",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        force = options["force"]
        papers_only = options["papers_only"]
        comments_only = options["comments_only"]

        # Process both by default if neither flag is set
        process_papers = not comments_only
        process_comments = not papers_only

        if process_comments:
            self.process_comments(batch_size, dry_run, force)

        if process_papers:
            self.process_papers(batch_size, dry_run, force)

    def process_comments(self, batch_size, dry_run, force):
        self.stdout.write(self.style.NOTICE("Processing comments..."))
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        # Get all comments that are not removed
        comments = RhCommentModel.objects.filter(is_removed=False).select_related(
            "thread", "created_by"
        )

        total_comments = comments.count()
        self.stdout.write(f"Found {total_comments} comments to process")

        processed = 0
        created = 0
        skipped = 0
        failed = 0

        # Process comments in batches
        for i, comment in enumerate(comments.iterator(chunk_size=batch_size)):
            processed += 1

            # Check if comment has thread
            if not hasattr(comment, "thread") or not comment.thread:
                skipped += 1
                continue

            # Get unified document for this comment's thread
            unified_document = getattr(comment.thread, "unified_document", None)
            if not unified_document:
                skipped += 1
                continue

            # Get hubs for the unified document
            hubs = unified_document.hubs.all()
            if not hubs.exists():
                skipped += 1
                continue

            # Check if the feed entry already exists
            if not force:
                existing_entries = []
                for hub in hubs:
                    hub_content_type = ContentType.objects.get_for_model(hub)
                    entry_exists = FeedEntry.objects.filter(
                        content_type=comment_content_type,
                        object_id=comment.id,
                        parent_content_type=hub_content_type,
                        parent_object_id=hub.id,
                    ).exists()
                    if entry_exists:
                        existing_entries.append(hub.name)

                if existing_entries:
                    skipped += 1
                    msg = (
                        f"Skipping comment {comment.id} - already has feed entries "
                        f"for hubs: {', '.join(existing_entries)}"
                    )
                    self.stdout.write(msg)
                    continue

            try:
                # Create feed entries
                if not dry_run:
                    with transaction.atomic():
                        for hub in hubs:
                            hub_content_type = ContentType.objects.get_for_model(hub)

                            # Create feed entry
                            content = serialize_feed_item(comment, comment_content_type)
                            metrics = serialize_feed_metrics(
                                comment, comment_content_type
                            )

                            FeedEntry.objects.create(
                                user=comment.created_by,
                                content=content,
                                content_type=comment_content_type,
                                object_id=comment.id,
                                action=FeedEntry.PUBLISH,
                                action_date=comment.created_date,
                                metrics=metrics,
                                parent_content_type=hub_content_type,
                                parent_object_id=hub.id,
                                unified_document=unified_document,
                            )

                created += 1
                if processed % 100 == 0 or processed == total_comments:
                    status = (
                        f"Processed {processed}/{total_comments} comments, "
                        f"created {created} feed entries, skipped {skipped}, "
                        f"failed {failed}"
                    )
                    self.stdout.write(status)

            except Exception as e:
                failed += 1
                error_msg = f"Failed to create feed entry for comment {comment.id}: {e}"
                logger.error(error_msg)
                self.stdout.write(self.style.ERROR(error_msg))

        # Final stats
        self.stdout.write(
            self.style.SUCCESS(
                f"Comments completed: processed {processed}/{total_comments}, "
                f"created {created} feed entries, skipped {skipped}, failed {failed}"
            )
        )

    def process_papers(self, batch_size, dry_run, force):
        self.stdout.write(self.style.NOTICE("Processing papers..."))
        paper_content_type = ContentType.objects.get_for_model(Paper)

        # Get all papers with a publish date
        papers = Paper.objects.filter(
            is_removed=False, paper_publish_date__isnull=False
        ).select_related("unified_document", "uploaded_by")

        total_papers = papers.count()
        self.stdout.write(f"Found {total_papers} papers to process")

        processed = 0
        created = 0
        skipped = 0
        failed = 0

        # Process papers in batches
        for i, paper in enumerate(papers.iterator(chunk_size=batch_size)):
            processed += 1

            # Check if paper has unified document
            unified_document = getattr(paper, "unified_document", None)
            if not unified_document:
                skipped += 1
                continue

            # Get hubs for the unified document
            hubs = unified_document.hubs.all()
            if not hubs.exists():
                skipped += 1
                continue

            # Check if the feed entry already exists
            if not force:
                existing_entries = []
                for hub in hubs:
                    hub_content_type = ContentType.objects.get_for_model(hub)
                    entry_exists = FeedEntry.objects.filter(
                        content_type=paper_content_type,
                        object_id=paper.id,
                        parent_content_type=hub_content_type,
                        parent_object_id=hub.id,
                    ).exists()
                    if entry_exists:
                        existing_entries.append(hub.name)

                if existing_entries:
                    skipped += 1
                    msg = (
                        f"Skipping paper {paper.id} - already has feed entries "
                        f"for hubs: {', '.join(existing_entries)}"
                    )
                    self.stdout.write(msg)
                    continue

            try:
                # Create feed entries
                if not dry_run:
                    with transaction.atomic():
                        for hub in hubs:
                            hub_content_type = ContentType.objects.get_for_model(hub)

                            # Create feed entry
                            content = serialize_feed_item(paper, paper_content_type)
                            metrics = serialize_feed_metrics(paper, paper_content_type)

                            FeedEntry.objects.create(
                                user=paper.uploaded_by,
                                content=content,
                                content_type=paper_content_type,
                                object_id=paper.id,
                                action=FeedEntry.PUBLISH,
                                action_date=paper.paper_publish_date,
                                metrics=metrics,
                                parent_content_type=hub_content_type,
                                parent_object_id=hub.id,
                                unified_document=unified_document,
                            )

                created += 1
                if processed % 100 == 0 or processed == total_papers:
                    status = (
                        f"Processed {processed}/{total_papers} papers, "
                        f"created {created} feed entries, skipped {skipped}, "
                        f"failed {failed}"
                    )
                    self.stdout.write(status)

            except Exception as e:
                failed += 1
                error_msg = f"Failed to create feed entry for paper {paper.id}: {e}"
                logger.error(error_msg)
                self.stdout.write(self.style.ERROR(error_msg))

        # Final stats
        self.stdout.write(
            self.style.SUCCESS(
                f"Papers completed: processed {processed}/{total_papers}, "
                f"created {created} feed entries, skipped {skipped}, failed {failed}"
            )
        )

        if dry_run:
            dry_run_msg = "This was a dry run. No feed entries were actually created."
            self.stdout.write(self.style.WARNING(dry_run_msg))
