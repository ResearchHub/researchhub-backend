from decimal import Decimal

from purchase.models import Fundraise, GrantApplication
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


def create_fundraise_post(
    created_by,
    title="Preregistration Post",
    goal_amount=Decimal("10000.00"),
    grant=None,
):
    """
    Helper to create a preregistration post with a fundraise.

    Args:
        created_by: User who creates the post and fundraise.
        title: Title for the preregistration post.
        goal_amount: Fundraise goal amount in USD.
        grant: Optional Grant instance. When provided, a
            GrantApplication linking the post to the grant
            is also created.

    Returns:
        A dict with keys: post, unified_document, fundraise,
        and grant_application (None when no grant is provided).
    """
    unified_doc = ResearchhubUnifiedDocument.objects.create(
        document_type=document_type.PREREGISTRATION,
    )
    post = ResearchhubPost.objects.create(
        title=title,
        created_by=created_by,
        document_type=document_type.PREREGISTRATION,
        renderable_text=title,
        unified_document=unified_doc,
    )
    fundraise = Fundraise.objects.create(
        unified_document=unified_doc,
        created_by=created_by,
        goal_amount=goal_amount,
        goal_currency="USD",
        status=Fundraise.OPEN,
    )

    grant_application = None
    if grant is not None:
        grant_application = GrantApplication.objects.create(
            grant=grant,
            preregistration_post=post,
            applicant=created_by,
        )

    return {
        "post": post,
        "unified_document": unified_doc,
        "fundraise": fundraise,
        "grant_application": grant_application,
    }
