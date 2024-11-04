from django.db import models
from django.db.models import UniqueConstraint
from django.utils.translation import gettext_lazy as _

from researchhub_case.constants.case_constants import APPROVED
from utils.models import DefaultModel, SoftDeletableModel


class PeerReview(SoftDeletableModel, DefaultModel):
    """
    Represents a peer review of a paper.
    This model manages the status of the peer review.
    The textual peer review content is stored as a comment thread.
    """

    class Status(models.TextChoices):
        """
        Represents the status of a peer review, from pending to approved.
        """

        APPROVED = APPROVED, _("Approved")
        CHANGES_REQUESTED = "CHANGES_REQUESTED", _("Changes Requested")
        PENDING = "PENDING", _("Pending")

    user = models.ForeignKey(
        "user.User",
        related_name="peer_reviews",
        blank=False,
        null=False,
        on_delete=models.CASCADE,
        db_comment="The user who is assigned to the peer review.",
    )

    paper = models.ForeignKey(
        "paper.Paper",
        related_name="peer_reviews",
        blank=False,
        null=False,
        on_delete=models.CASCADE,
        db_comment="The paper that is under peer review.",
    )

    comment_thread = models.ForeignKey(
        "researchhub_comment.RhCommentThreadModel",
        blank=False,
        null=True,
        related_name="peer_review",
        on_delete=models.CASCADE,
        db_comment="The textual peer review content is stored in the comment thread.",
    )

    status = models.TextField(
        choices=Status.choices,
        default=Status.PENDING,
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["user", "paper"],
                name="unique_paper_user",
            ),
        ]
