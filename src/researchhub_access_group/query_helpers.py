from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef, Q

from researchhub_access_group.constants import NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument


def unified_document_user_access_q(
    user, *, unified_document_id_lookup: str = "unified_document_id"
) -> Q:
    """
    Return a Q object that is true when ``user`` may access a unified document
    via direct or organization permission rows.

    A NO_ACCESS row for the same user/document revokes access even when a stale
    VIEWER (or other) row still exists; the Permission model has no uniqueness
    constraint on (user, document).
    """
    ud_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
    user_perms = Permission.objects.filter(
        content_type=ud_ct,
        object_id=OuterRef(unified_document_id_lookup),
        user=user,
    )
    allowed = user_perms.exclude(access_type=NO_ACCESS)
    revoked = user_perms.filter(access_type=NO_ACCESS)

    org_perms = Permission.objects.filter(
        content_type=ud_ct,
        object_id=OuterRef(unified_document_id_lookup),
        organization__permissions__user=user,
    )
    org_allowed = org_perms.exclude(access_type=NO_ACCESS)
    org_revoked = org_perms.filter(access_type=NO_ACCESS)

    return (Exists(allowed) & ~Exists(revoked)) | (
        Exists(org_allowed) & ~Exists(org_revoked)
    )
