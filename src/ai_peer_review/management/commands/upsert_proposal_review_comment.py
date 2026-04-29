"""
Create or update the Tiptap Rh comment for a completed :class:`ProposalReview`.

Usage:
    python manage.py upsert_proposal_review_comment 42
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ai_peer_review.models import ProposalReview
from ai_peer_review.services.proposal_review_comment_service import (
    resolve_ai_expert_email,
    upsert_proposal_review_comment,
)


class Command(BaseCommand):
    help = (
        "Upsert the AI proposal review comment (Rh thread) for a ProposalReview by id"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "review_id",
            type=int,
            help="Primary key of the ProposalReview (ai_peer_review_proposalreview.id)",
        )

    def handle(self, *args, **options):
        review_id: int = options["review_id"]
        try:
            review = ProposalReview.objects.select_related("unified_document").get(
                pk=review_id
            )
        except ProposalReview.DoesNotExist as e:
            raise CommandError(f"ProposalReview id={review_id} not found.") from e

        comment = upsert_proposal_review_comment(review)
        if comment is None:
            self.stdout.write(
                self.style.WARNING(
                    "No comment written (expected status=completed, a post on the "
                    f"unified document, and user {resolve_ai_expert_email()})."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Upserted comment id={comment.id} for ProposalReview id={review_id}."
            )
        )
