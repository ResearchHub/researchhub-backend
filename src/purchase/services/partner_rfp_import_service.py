"""Import partner RFP pages and export their catalog metadata."""

import html
from decimal import Decimal

from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from purchase.models import Grant
from purchase.related_models.constants.currency import USD
from purchase.services.grant_creation_service import GrantCreationService
from purchase.services.partner_rfp_catalog import (
    PartnerRfpTopic,
    permanent_rfp_id,
    validate_https_url,
    validate_partner_organization,
)
from research_ai.models import CoverImageGeneration
from research_ai.services.cover_image_service import CoverImageService
from researchhub_document.models import (
    DocumentFilter,
    ResearchhubPost,
    ResearchhubUnifiedDocument,
)
from researchhub_document.related_models.constants.document_type import GRANT
from user.models import User


class PartnerRfpImportService:
    def __init__(
        self,
        *,
        partner_organization: str,
        cover_service=None,
        grant_creation_service=None,
    ):
        self.partner_organization = validate_partner_organization(partner_organization)
        self.cover_service = cover_service or CoverImageService()
        self.grant_creation_service = grant_creation_service or GrantCreationService()

    @transaction.atomic
    def import_topic(
        self,
        topic: PartnerRfpTopic,
        *,
        owner: User,
        is_public: bool = False,
        grant_amount: Decimal = Decimal(0),
        organization: str = "",
    ) -> tuple[ResearchhubPost, bool]:
        # Serialize concurrent runs for this owner; source_id's unique constraint
        # also prevents duplicate imports across owners/processes.
        User.objects.select_for_update().get(pk=owner.pk)
        post = (
            ResearchhubPost.objects.select_related("unified_document__document_filter")
            .filter(external_source_id=topic.source_id(self.partner_organization))
            .first()
        )
        created = post is None
        if post is not None:
            if post.created_by_id != owner.pk or post.document_type != GRANT:
                raise ValueError(
                    f"{topic.topic}: existing import has another owner/type"
                )
            if post.unified_document.is_removed:
                raise ValueError(
                    f"{topic.topic}: imported post was removed; do not recreate"
                )
            if not getattr(
                post.unified_document.document_filter, "is_excluded_in_feed", False
            ):
                raise ValueError(
                    f"{topic.topic}: imported post no longer excluded from feeds"
                )
            # Existing pages/visibility/grants are never overwritten on a retry.
        else:
            document = ResearchhubUnifiedDocument.objects.create(
                document_type=GRANT,
                is_public=is_public,
                document_filter=DocumentFilter.objects.create(is_excluded_in_feed=True),
            )
            post = ResearchhubPost.objects.create(
                external_source_id=topic.source_id(self.partner_organization),
                created_by=owner,
                document_type=GRANT,
                title=topic.title,
                slug=slugify(topic.title),
                renderable_text=self.page_html(topic.summary),
                unified_document=document,
                # Public source URLs belong in preview_img, never image (a key).
                preview_img=topic.image,
            )
            post.reset_post_authors([owner.author_profile.pk])

        if not post.unified_document.grants.exists():
            # This internal batch accepts zero; the regular API serializer keeps
            # requiring a positive amount. Retain field validation and the domain
            # service's authorization, duplicate prevention and pool creation.
            amount = serializers.DecimalField(
                max_digits=19, decimal_places=2, min_value=Decimal(0)
            ).run_validation(grant_amount)
            organization = serializers.CharField(
                max_length=255, allow_blank=True
            ).run_validation(organization)
            description = serializers.CharField().run_validation(topic.summary)
            self.grant_creation_service.create_grant(
                created_by=owner,
                unified_document=post.unified_document,
                amount=amount,
                currency=USD,
                organization=organization,
                description=description,
                status=Grant.OPEN,
            )
        return post, created

    @staticmethod
    def page_html(summary: str) -> str:
        return "\n".join(
            "<p>" + html.escape(paragraph).replace("\n", "<br>") + "</p>"
            for paragraph in summary.split("\n\n")
        )

    def ensure_cover(self, post: ResearchhubPost, topic: PartnerRfpTopic) -> None:
        if post.image or post.preview_img:
            return
        # Reuse a completed generation if the process previously stopped after
        # paying for/storing it but before it could attach the key to the post.
        generation = (
            CoverImageGeneration.objects.filter(
                created_by=post.created_by,
                document_type=GRANT,
                title=post.title,
                subtitle=topic.topic,
                status=CoverImageGeneration.Status.COMPLETED,
            )
            .order_by("-id")
            .first()
        )
        if generation is None:
            generation = self.cover_service.generate_for_batch(
                user=post.created_by,
                document_type=GRANT,
                title=post.title,
                subtitle=topic.topic,
            )
        if generation.status != CoverImageGeneration.Status.COMPLETED:
            raise ValueError(f"Cover failed for {topic.topic}: {generation.error}")
        url = validate_https_url(self.cover_service.image_url(generation.image_key))
        post.image = generation.image_key
        post.preview_img = url
        post.save(update_fields=["image", "preview_img", "updated_date"])

    def export(
        self,
        topics,
        *,
        owner,
        require_images=False,
    ) -> dict:
        posts = {
            post.external_source_id: post
            for post in ResearchhubPost.objects.filter(
                external_source_id__in=[
                    topic.source_id(self.partner_organization) for topic in topics
                ],
                created_by=owner,
            ).select_related("unified_document__document_filter")
        }
        rfps = []
        for topic in topics:
            post = posts.get(topic.source_id(self.partner_organization))
            if post is None or post.unified_document.is_removed:
                raise ValueError(f"Missing imported RFP: {topic.topic}")
            if not getattr(
                post.unified_document.document_filter, "is_excluded_in_feed", False
            ):
                raise ValueError(f"RFP no longer excluded from feeds: {topic.topic}")
            image = post.preview_img or (
                self.cover_service.image_url(post.image) if post.image else None
            )
            if image:
                validate_https_url(image)
            elif require_images:
                raise ValueError(f"RFP has no image: {topic.topic}")
            rfp = {
                "id": permanent_rfp_id(post.pk),
                "title": topic.title,
                "summary": topic.summary,
                "image": image,
                "keywords": list(topic.keywords),
                "live": True,
            }
            rfps.append(rfp)
        return {"source": "researchhub", "rfps": rfps}
