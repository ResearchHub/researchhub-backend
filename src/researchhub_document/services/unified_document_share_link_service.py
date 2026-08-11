import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.related_models.unified_document_share_link_model import (
    UnifiedDocumentShareLink,
)
from user.models import User

SHARE_LINK_TTL = timedelta(days=30)
SHARE_LINK_TOKEN_BYTES = 32

# Query parameter carrying the share token on ordinary document requests.
SHARE_TOKEN_PARAM = "st"


def get_shared_unified_document_id(request) -> int | None:
    """Resolve which unified document a request's share token grants access to.

    Returns ``None`` when there is no token or the token is not live. Callers
    must compare the id against the document actually being served: the token
    authorizes one document, never the request as a whole.
    """
    token = request.query_params.get(SHARE_TOKEN_PARAM)
    return UnifiedDocumentShareLinkService().resolve_unified_document_id(token)


class UnifiedDocumentShareLinkService:
    """Generate and resolve anonymous share links for proposals."""

    def create_or_get(
        self, unified_document_id: int, user: User
    ) -> tuple[UnifiedDocumentShareLink, bool]:
        """Return the proposal's share link, generating one when needed.

        A live link is returned untouched no matter which eligible user asks,
        so a second caller can never invalidate a URL that has already been
        handed out. An expired link is regenerated in place with a new token,
        which permanently retires the previous URL.
        """
        with transaction.atomic():
            unified_document = (
                ResearchhubUnifiedDocument.objects.select_for_update().get(
                    pk=unified_document_id
                )
            )
            self._assert_can_share(unified_document, user)

            link = UnifiedDocumentShareLink.objects.filter(
                unified_document=unified_document
            ).first()

            if link is not None and not link.is_expired():
                return link, False

            link, _ = UnifiedDocumentShareLink.objects.update_or_create(
                unified_document=unified_document,
                defaults={
                    "token": secrets.token_urlsafe(SHARE_LINK_TOKEN_BYTES),
                    "expires_at": timezone.now() + SHARE_LINK_TTL,
                    "created_by": user,
                },
            )
            return link, True

    def resolve_unified_document_id(self, token: str) -> int | None:
        """Return the unified document id a live token grants access to.

        Unknown tokens, expired links, removed documents, and non-proposals all
        answer ``None`` so callers cannot tell them apart. The expiry bound is
        the inverse of ``is_expired()``.
        """
        # Absent tokens are the common case, so skip the query entirely.
        if not token:
            return None

        return (
            UnifiedDocumentShareLink.objects.filter(
                token=token,
                expires_at__gt=timezone.now(),
                unified_document__is_removed=False,
                unified_document__document_type=PREREGISTRATION,
            )
            .values_list("unified_document_id", flat=True)
            .first()
        )

    def _assert_can_share(
        self, unified_document: ResearchhubUnifiedDocument, user: User
    ) -> None:
        if unified_document.document_type != PREREGISTRATION:
            raise ValueError("Only proposals can be shared.")
        if not self._is_eligible(unified_document, user):
            raise PermissionError(
                "Only moderators, the proposal's authors, or the creator of a "
                "grant it applied to can generate a share link."
            )

    def _is_eligible(
        self, unified_document: ResearchhubUnifiedDocument, user: User
    ) -> bool:
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if user.is_moderator_or_editor():
            return True

        # Spans every version of the proposal, since authorship and grant
        # applications are recorded against individual post versions.
        return (
            ResearchhubPost.objects.filter(unified_document=unified_document)
            .filter(
                Q(created_by=user)
                | Q(authors__user=user)
                | Q(grant_applications__grant__created_by=user)
            )
            .exists()
        )
