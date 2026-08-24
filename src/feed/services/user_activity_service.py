"""Assembly of the documents a user is involved with."""

from django.db.models import Q

from purchase.models import Fundraise
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.utils import get_funded_fundraise_ids
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class UserActivityService:
    """Resolve which documents a user is involved with.

    Only OPEN and COMPLETED grants count as involvement; PENDING, CLOSED, and
    DECLINED grants are moderation or archival states that stay out of feeds.
    """

    def get_involved_document_ids(self, user_id: int) -> set[int]:
        """Return the unified document IDs the user is involved with."""
        involved_grants = Grant.objects.filter(
            Q(created_by_id=user_id)
            | Q(contacts__id=user_id)
            | Q(applications__applicant_id=user_id),
            status__in=[Grant.OPEN, Grant.COMPLETED],
            unified_document__is_public=True,
        )
        applied_document_ids = GrantApplication.objects.filter(
            grant__in=involved_grants,
        ).values_list("preregistration_post__unified_document_id", flat=True)
        created_document_ids = ResearchhubPost.objects.filter(
            created_by_id=user_id,
            document_type=PREREGISTRATION,
        ).values_list("unified_document_id", flat=True)
        funded_document_ids = Fundraise.objects.filter(
            id__in=get_funded_fundraise_ids(user_id),
        ).values_list("unified_document_id", flat=True)

        return (
            set(involved_grants.values_list("unified_document_id", flat=True))
            | set(applied_document_ids)
            | set(created_document_ids)
            | set(funded_document_ids)
        )
