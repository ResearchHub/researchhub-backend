from django.db import models
from django.db.models import CASCADE

from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel


PROPOSAL_POST_LOOKUP = "preregistration_post"
PROPOSAL_DOCUMENT_LOOKUP = f"{PROPOSAL_POST_LOOKUP}__unified_document"


def approved_proposal_filters(application_lookup=""):
    """Return ORM filters for an approved proposal on a GrantApplication path."""
    proposal_post_lookup = (
        f"{application_lookup}__{PROPOSAL_POST_LOOKUP}"
        if application_lookup
        else PROPOSAL_POST_LOOKUP
    )
    proposal_document_lookup = (
        f"{application_lookup}__{PROPOSAL_DOCUMENT_LOOKUP}"
        if application_lookup
        else PROPOSAL_DOCUMENT_LOOKUP
    )
    return {
        f"{proposal_post_lookup}__document_type": PREREGISTRATION,
        f"{proposal_document_lookup}__status": ResearchhubUnifiedDocument.APPROVED,
        f"{proposal_document_lookup}__is_removed": False,
    }


class GrantApplicationQuerySet(models.QuerySet):
    """QuerySet for GrantApplication with common filters."""

    def for_user_grants(self, user):
        """Filter applications for grants created by the given user."""
        return self.filter(grant__created_by=user)

    def with_approved_proposal(self):
        """Only include applications whose proposal document is approved."""
        return self.filter(**approved_proposal_filters())

    def fundraise_ids(self) -> set[int]:
        """Return set of fundraise IDs for these applications."""
        return set(
            self.values_list(
                "preregistration_post__unified_document__fundraises__id", flat=True
            )
        )


class GrantApplication(DefaultModel):
    """Simple linking model between grants and preregistration posts."""

    objects = GrantApplicationQuerySet.as_manager()

    grant = models.ForeignKey(
        "purchase.Grant", on_delete=CASCADE, related_name="applications"
    )

    preregistration_post = models.ForeignKey(
        "researchhub_document.ResearchhubPost",
        on_delete=CASCADE,
        related_name="grant_applications",
    )

    applicant = models.ForeignKey(
        "user.User", on_delete=CASCADE, related_name="grant_applications"
    )

    class Meta:
        unique_together = ("grant", "preregistration_post")
        indexes = [
            models.Index(fields=["grant"]),
            models.Index(fields=["applicant"]),
        ]

    def __str__(self):
        return f"Grant Application: {self.grant} - {self.preregistration_post}"

    def has_approved_proposal(self):
        proposal = getattr(self, "preregistration_post", None)
        proposal_document = getattr(proposal, "unified_document", None)
        return (
            proposal is not None
            and proposal.document_type == PREREGISTRATION
            and proposal_document is not None
            and not proposal_document.is_removed
            and proposal_document.status == ResearchhubUnifiedDocument.APPROVED
        )
