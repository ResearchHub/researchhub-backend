"""
Backfill Review.is_assessed for reviews on comments that were tipped or
awarded a bounty by the foundation (community) account.

Mirrors the rules in review/signals/review_signals.py.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from review.models import Review
from user.models import User


class Command(BaseCommand):
    help = (
        "Set Review.is_assessed=True for reviews whose underlying comment was "
        "tipped or awarded a bounty by the foundation (community) account."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # community = User.objects.get_community_account()
        community = User.objects.get(id=1)
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)

        tipped_comment_ids = set(
            Purchase.objects.filter(
                user=community,
                content_type=comment_ct,
            ).values_list("object_id", flat=True)
        )

        awarded_comment_ids = set(
            BountySolution.objects.filter(
                status=BountySolution.Status.AWARDED,
                content_type=comment_ct,
                bounty__created_by=community,
            ).values_list("object_id", flat=True)
        )

        comment_ids = tipped_comment_ids | awarded_comment_ids

        reviews_to_update = Review.objects.filter(
            is_assessed=False,
            content_type=comment_ct,
            object_id__in=comment_ids,
        )
        count = reviews_to_update.count()

        self.stdout.write(
            f"Tipped comments: {len(tipped_comment_ids)} | "
            f"Awarded comments: {len(awarded_comment_ids)} | "
            f"Reviews to update: {count}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
            return

        updated = reviews_to_update.update(is_assessed=True)
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} reviews."))
