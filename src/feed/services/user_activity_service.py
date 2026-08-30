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

    Only OPEN and COMPLETED grants count. Visibility is applied by the feed.
    """

    def get_involved_document_ids(self, user_id: int) -> set[int]:
        """Return the unified document IDs the user is involved with."""
        grant_documents = dict(
            Grant.objects.filter(
                Q(created_by_id=user_id)
                | Q(contacts__id=user_id)
                | Q(applications__applicant_id=user_id),
                status__in=[Grant.OPEN, Grant.COMPLETED],
            )
            .distinct()
            .values_list("id", "unified_document_id")
        )
        document_ids = set(grant_documents.values())
        document_ids.update(
            GrantApplication.objects.filter(grant_id__in=grant_documents).values_list(
                "preregistration_post__unified_document_id",
                flat=True,
            )
        )
        document_ids.update(
            ResearchhubPost.objects.filter(
                created_by_id=user_id,
                document_type=PREREGISTRATION,
            ).values_list("unified_document_id", flat=True)
        )
        document_ids.update(
            Fundraise.objects.filter(
                id__in=get_funded_fundraise_ids(user_id),
            ).values_list("unified_document_id", flat=True)
        )
        return document_ids
