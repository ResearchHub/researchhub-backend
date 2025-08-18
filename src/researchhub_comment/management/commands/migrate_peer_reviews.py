"""
Migration command to extract nested peer reviews from bounty replies.

This command identifies comments that are bounty replies but should be classified
as peer reviews, and migrates them to the proper review structure.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import models

from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel


class Command(BaseCommand):
    help = "Migrate bounty replies that are actually peer reviews to the proper review structure"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Get content type for RhCommentModel
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        # Find comments where:
        # - comment_type = "REVIEW"
        # - parent_id is not null (nested comments)
        # - comment_content_type = "QUILL_EDITOR"
        # - AND they have a corresponding record in review_review table
        target_comments = RhCommentModel.objects.filter(
            comment_type=COMMUNITY_REVIEW,
            parent__isnull=False,
            comment_content_type=QUILL_EDITOR,
        ).filter(
            # Ensure there's a record in review_review table for this comment
            reviews__content_type=comment_content_type,
            reviews__object_id=models.F("id"),
        )

        count = target_comments.count()

        self.stdout.write(
            self.style.SUCCESS(f"Found {count} comments that match the criteria:")
        )
        self.stdout.write("  - comment_type = " + f'"{COMMUNITY_REVIEW}"')
        self.stdout.write("  - parent_id is not null (nested comments)")
        self.stdout.write("  - comment_content_type = " + f'"{QUILL_EDITOR}"')
        self.stdout.write("  - HAS a corresponding record in review_review table")

        if count > 0:
            self.stdout.write("\nSample comments:")
            for i, comment in enumerate(target_comments[:5]):  # Show first 5
                # Get the review record for this comment
                review = comment.reviews.first()
                self.stdout.write(
                    f"  {i+1}. Comment ID: {comment.id}, "
                    f"Parent ID: {comment.parent_id}, "
                    f"Review ID: {review.id if review else 'None'}, "
                    f"Review Score: {review.score if review else 'None'}, "
                    f"Created: {comment.created_date}"
                )

            if count > 5:
                self.stdout.write(f"  ... and {count - 5} more")

        # Also show how many comments match the criteria but DON'T have review records
        comments_without_reviews = (
            RhCommentModel.objects.filter(
                comment_type=COMMUNITY_REVIEW,
                parent__isnull=False,
                comment_content_type=QUILL_EDITOR,
            )
            .exclude(
                # Comments that DON'T have entries in review_review table
                reviews__content_type=comment_content_type,
                reviews__object_id=models.F("id"),
            )
            .count()
        )

        self.stdout.write(
            f"\nComments matching criteria but WITHOUT review_review records: {comments_without_reviews}"
        )

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("This is a placeholder command.")
        self.stdout.write("Next steps:")
        self.stdout.write(
            "1. Analyze these comments to determine if they are actually peer reviews"
        )
        self.stdout.write("2. Check if they have associated bounty solutions")
        self.stdout.write(
            "3. Implement the migration logic to convert them to proper peer reviews"
        )
        self.stdout.write("4. Update the review_review table accordingly")

        if not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nNote: This command currently only analyzes data. "
                    "Migration logic needs to be implemented."
                )
            )
