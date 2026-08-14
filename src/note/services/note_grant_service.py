from rest_framework.exceptions import NotFound
from rest_framework.serializers import IntegerField, ValidationError

from purchase.models import Grant
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.models import User


def resolve_selected_grant(
    grant_id: object,
    document_type: str | None,
    user: User,
) -> Grant | None:
    """Resolve a visible, active grant for a preregistration note."""
    if document_type != PREREGISTRATION:
        raise ValidationError(
            {"selected_grant": "Only preregistration notes can select a grant."}
        )
    if grant_id is None:
        return None

    validated_grant_id = IntegerField(min_value=1).run_validation(grant_id)
    visible_document_ids = ResearchhubPost.objects.visible_to(user).values(
        "unified_document_id"
    )
    grant = Grant.objects.filter(
        id=validated_grant_id,
        unified_document_id__in=visible_document_ids,
    ).first()
    if grant is None:
        raise NotFound("Grant not found.")
    if not grant.is_active():
        raise ValidationError(
            {"selected_grant": "Grant is no longer accepting applications."}
        )
    return grant
