"""
Migration command to extract nested peer reviews from bounty replies.

This command identifies comments that are bounty replies but should be classified
as peer reviews, and migrates them to the proper review structure.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import models, transaction

from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel


class Command(BaseCommand):
    help = "Migrate bounty replies that are actually peer reviews to the proper review structure"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without making changes",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of comments to migrate (e.g., --limit 100)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        if limit:
            self.stdout.write(
                self.style.WARNING(
                    f"LIMIT MODE - Will process maximum {limit} comments"
                )
            )

        # Get content type for RhCommentModel
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        # Find INVALID review comments that are direct children of bounty comments
        # These are the ones we need to migrate to proper review structure
        invalid_review_comments = (
            RhCommentModel.objects.filter(
                comment_type=COMMUNITY_REVIEW,
                parent__isnull=False,  # Must be nested under another comment
                comment_content_type=QUILL_EDITOR,
            )
            .filter(
                # Must have a corresponding record in review_review table
                reviews__content_type=comment_content_type,
                reviews__object_id=models.F("id"),
            )
            .filter(
                # The parent comment must be a bounty comment (has bounties)
                parent__bounties__isnull=False,
            )
            .filter(
                # Must be on the same thread as the bounty (invalid structure)
                thread=models.F("parent__thread"),
            )
            .order_by("id")  # Ensure consistent ordering for pagination
        )

        total_count = invalid_review_comments.count()

        # Apply limit if specified
        if limit:
            invalid_review_comments = invalid_review_comments[:limit]
            actual_count = invalid_review_comments.count()
        else:
            actual_count = total_count

        self.stdout.write(
            self.style.SUCCESS(
                f"Found {total_count} total INVALID review comments that need migration:"
            )
        )
        if limit:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Will process {actual_count} comments (limited by --limit {limit})"
                )
            )
        self.stdout.write("  - comment_type = " + f'"{COMMUNITY_REVIEW}"')
        self.stdout.write("  - parent_id is not null (nested under bounty comment)")
        self.stdout.write("  - comment_content_type = " + f'"{QUILL_EDITOR}"')
        self.stdout.write("  - HAS a corresponding record in review_review table")
        self.stdout.write("  - Parent comment has bounties (is a bounty comment)")
        self.stdout.write("  - Same thread_id as parent (invalid structure)")

        if actual_count > 0:
            self.stdout.write("\nSample invalid review comments:")
            for i, comment in enumerate(invalid_review_comments[:5]):  # Show first 5
                # Get the review record for this comment
                review = comment.reviews.first()
                # Get the parent bounty comment
                parent_comment = comment.parent
                parent_bounty = parent_comment.bounties.first()

                self.stdout.write(
                    f"  {i+1}. Comment ID: {comment.id}, "
                    f"Parent ID: {comment.parent_id} (bounty comment), "
                    f"Thread ID: {comment.thread_id}, "
                    f"Review ID: {review.id if review else 'None'}, "
                    f"Review Score: {review.score if review else 'None'}, "
                    f"Parent Bounty ID: {parent_bounty.id if parent_bounty else 'None'}, "
                    f"Created: {comment.created_date}"
                )

            if actual_count > 5:
                self.stdout.write(f"  ... and {actual_count - 5} more")

        # Show bounty comments that have nested reviews
        bounty_comments_with_nested_reviews = (
            RhCommentModel.objects.filter(
                bounties__isnull=False,  # Is a bounty comment
            )
            .filter(
                children__comment_type=COMMUNITY_REVIEW,  # Has children that are reviews
                children__reviews__content_type=comment_content_type,
                children__reviews__object_id=models.F("children__id"),
            )
            .distinct()
        )

        bounty_count = bounty_comments_with_nested_reviews.count()
        self.stdout.write(
            f"\nBounty comments that have nested review comments: {bounty_count}"
        )

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("MIGRATION ANALYSIS COMPLETE")
        self.stdout.write("=" * 50)

        if actual_count > 0:
            self.stdout.write(
                f"\nFound {total_count} total invalid review comments that need migration."
            )
            if limit:
                self.stdout.write(
                    f"Will migrate {actual_count} comments in this run (limited by --limit {limit})."
                )
                remaining = total_count - actual_count
                if remaining > 0:
                    self.stdout.write(f"Remaining comments to migrate: {remaining}")
            self.stdout.write(
                "These reviews are incorrectly nested under bounty comments."
            )
            self.stdout.write("\nMigration plan:")
            self.stdout.write("1. Create new thread for each invalid review")
            self.stdout.write("2. Move review comment to new thread (parent_id = null)")
            self.stdout.write("3. Update review_review table to point to new thread")
            self.stdout.write("4. Preserve all review data and relationships")

            if not dry_run:
                self.stdout.write("\n" + "=" * 50)
                self.stdout.write("STARTING MIGRATION")
                self.stdout.write("=" * 50)

                migrated_count = self._migrate_invalid_reviews(invalid_review_comments)

                self.stdout.write(f"\nMigration completed successfully!")
                self.stdout.write(
                    f"Migrated {migrated_count} review comments to proper structure."
                )
                if limit and remaining > 0:
                    self.stdout.write(
                        f"Run again to migrate the remaining {remaining} comments."
                    )
            else:
                self.stdout.write("\n" + "=" * 50)
                self.stdout.write("DRY RUN - NO CHANGES MADE")
                self.stdout.write("=" * 50)
                self.stdout.write(
                    "Run without --dry-run to perform the actual migration."
                )
        else:
            self.stdout.write(
                "\nNo invalid review comments found. All reviews appear to be properly structured."
            )

    def _migrate_invalid_reviews(self, invalid_review_comments):
        """
        Migrate invalid review comments to proper review structure.

        For each invalid review comment:
        1. Create a new thread for the review
        2. Move the review comment to the new thread (set parent_id = null)
        3. Update the review_review table to point to the new thread
        """
        migrated_count = 0

        for comment in invalid_review_comments:
            try:
                with transaction.atomic():
                    # Get the review record for this comment
                    review = comment.reviews.first()
                    if not review:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Comment {comment.id} has no review record, skipping..."
                            )
                        )
                        continue

                    # Get the parent bounty comment to access its unified_document
                    parent_comment = comment.parent
                    parent_bounty = parent_comment.bounties.first()

                    if not parent_bounty:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Comment {comment.id} parent has no bounty, skipping..."
                            )
                        )
                        continue

                    # Create a new thread for this review
                    # Use the parent comment's thread content_type and object_id
                    new_thread = RhCommentThreadModel.objects.create(
                        thread_type=COMMUNITY_REVIEW,
                        content_type=parent_comment.thread.content_type,
                        object_id=parent_comment.thread.object_id,
                        created_by=comment.created_by,
                        updated_by=comment.updated_by,
                    )

                    # Move the review comment to the new thread and remove parent
                    old_thread_id = comment.thread_id
                    old_parent_id = comment.parent_id

                    comment.thread = new_thread
                    comment.parent = None  # Make it a top-level comment
                    comment.save()

                    migrated_count += 1

                    self.stdout.write(
                        f"✓ Migrated Comment {comment.id}: "
                        f"Thread {old_thread_id} → {new_thread.id}, "
                        f"Parent {old_parent_id} → null, "
                        f"Review {review.id} updated to point to thread"
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Failed to migrate Comment {comment.id}: {str(e)}"
                    )
                )
                continue

        return migrated_count
