from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from purchase.models import Grant
from purchase.services.funding_pool_service import FundingPoolService
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from user.models import User


class GrantCreationService:
    def __init__(self, funding_pool_service=None, document_editing_permission=None):
        self.funding_pool_service = funding_pool_service or FundingPoolService()
        self.document_editing_permission = (
            document_editing_permission or HasDocumentEditingPermission()
        )

    @transaction.atomic
    def create_grant(self, *, created_by, unified_document, contact_ids=(), **fields):
        """Attach a grant only to an authorized post, once per document."""
        if not created_by or not created_by.is_authenticated:
            raise PermissionDenied("Authentication is required to create a grant.")

        # Serialize creation on the document, including when it has no grant yet.
        unified_document = ResearchhubUnifiedDocument.objects.select_for_update().get(
            pk=unified_document.pk
        )
        posts = unified_document.posts.select_related("note__organization")
        if not created_by.moderator and not any(
            self.document_editing_permission.can_edit_post(post, created_by)
            for post in posts
        ):
            raise PermissionDenied("You cannot create a grant for this document.")

        if Grant.objects.filter(unified_document=unified_document).exists():
            raise ValidationError("This document already has a grant.")

        grant = Grant.objects.create(
            created_by=created_by,
            unified_document=unified_document,
            **fields,
        )
        if contact_ids:
            grant.contacts.set(User.objects.filter(id__in=contact_ids))
        self.funding_pool_service.create_pool_for_grant(grant)
        return grant
