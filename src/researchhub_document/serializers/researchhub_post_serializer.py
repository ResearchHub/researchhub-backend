import logging

from django.core.files.storage import default_storage
from django.db.models import Count
from rest_framework.serializers import (
    CharField,
    IntegerField,
    ModelSerializer,
    Serializer,
    SerializerMethodField,
)

from ai_peer_review.models import ProposalReview
from ai_peer_review.serializers import ProposalReviewSerializer
from discussion.models import Vote
from discussion.serializers import (
    DynamicVoteSerializer,  # Import is needed for discussion serializer imports
    GenericReactionSerializerMixin,
)
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from purchase.models import Fundraise, GrantApplication, Purchase
from researchhub.serializers import (
    DynamicModelFieldSerializer,
    ModeratedDocumentStatusSerializerMixin,
)
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from review.serializers.review_serializer import DynamicReviewSerializer
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorSerializer,
    DynamicUserSerializer,
    UserSerializer,
)
from utils.http import get_user_from_request

logger = logging.getLogger(__name__)


class CompletedProposalCandidateSerializer(ModelSerializer):
    """Serialize a completed proposal that can receive a registered report."""

    completed_fundraise = SerializerMethodField()
    image_url = SerializerMethodField()
    journey_id = IntegerField(read_only=True)
    unified_document_id = IntegerField(read_only=True)

    class Meta:
        model = ResearchhubPost
        fields = [
            "id",
            "title",
            "slug",
            "created_date",
            "document_type",
            "image_url",
            "unified_document_id",
            "journey_id",
            "completed_fundraise",
        ]

    def get_completed_fundraise(
        self, post: ResearchhubPost
    ) -> dict[str, int | str] | None:
        """Return the completed fundraise summary for the proposal."""
        fundraises = getattr(post.unified_document, "completed_fundraises", None)
        if fundraises is None:
            completed_fundraise = (
                post.unified_document.fundraises.filter(
                    status=Fundraise.COMPLETED,
                )
                .order_by("-created_date", "-id")
                .first()
            )
        else:
            completed_fundraise = fundraises[0] if fundraises else None
        if completed_fundraise is None:
            return None
        return {
            "id": completed_fundraise.id,
            "status": completed_fundraise.status,
            "goal_amount": str(completed_fundraise.goal_amount),
            "goal_currency": completed_fundraise.goal_currency,
        }

    def get_image_url(self, post: ResearchhubPost) -> str | None:
        """Return the proposal image URL, if one exists."""
        if not post.image:
            return None
        return default_storage.url(post.image)

class RegisteredReportCreateSerializer(Serializer):
    """Validate a registered report creation request."""

    proposal_id = IntegerField()
    title = CharField()
    renderable_text = CharField()
    full_src = CharField()
    note_id = IntegerField(required=False, allow_null=True)
    editor_type = CharField(required=False, allow_blank=True, allow_null=True)
    image = CharField(required=False, allow_blank=True, allow_null=True)
    preview_img = CharField(required=False, allow_blank=True, allow_null=True)


class ResearchhubPostSerializer(
    ModelSerializer,
    GenericReactionSerializerMixin,
    ModeratedDocumentStatusSerializerMixin,
):
    class Meta(object):
        model = ResearchhubPost
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            "authors",
            "boost_amount",
            "id",
            "created_by",
            "created_date",
            "discussion_count",
            "document_type",
            "doi",
            "editor_type",
            "full_markdown",
            "grants",
            "hubs",
            "id",
            "image",
            "image_url",
            "is_latest_version",
            "is_removed",
            "is_root_version",
            "note",
            "peer_reviews",
            "post_src",
            "preview_img",
            "renderable_text",
            "reviewed_by",
            "reviewed_date",
            "slug",
            "status",
            "title",
            "unified_document_id",
            "unified_document",
            "version_number",
            "updated_date",
            "bounty_type",
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            "authors",
            "id",
            "created_by",
            "created_date",
            "discussion_count",
            "grants",
            "image_url",
            "is_latest_version",
            "is_root_version",
            "note",
            "post_src",
            "unified_document_id",
            "version_number",
            "boost_amount",
            "is_removed",
            "updated_date",
        ]

    # GenericReactionSerializerMixin
    promoted = SerializerMethodField()
    boost_amount = SerializerMethodField()
    user_flag = SerializerMethodField()

    # local
    authors = SerializerMethodField()
    created_by = SerializerMethodField(method_name="get_created_by")
    peer_reviews = SerializerMethodField()
    full_markdown = SerializerMethodField(method_name="get_full_markdown")
    grants = SerializerMethodField()
    hubs = SerializerMethodField(method_name="get_hubs")
    image = CharField(write_only=True, required=False, allow_null=True)
    image_url = SerializerMethodField()
    is_removed = SerializerMethodField()
    note = SerializerMethodField()
    post_src = SerializerMethodField(method_name="get_post_src")
    unified_document = SerializerMethodField()
    unified_document_id = SerializerMethodField(method_name="get_unified_document_id")

    def get_authors(self, post):
        # Probably legacy scenario, before ELN release
        authors = list(post.authors.all())
        if len(authors) == 0:
            authors.append(post.created_by.author_profile)
        else:
            authors = post.authors

        serializer = AuthorSerializer(
            authors,
            context=self.context,
            many=True,
        )
        return serializer.data

    def get_post_src(self, instance):
        try:
            if instance.document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                return instance.discussion_src.url
            else:
                return instance.eln_src.url
        except Exception:
            return None

    def get_created_by(self, instance):
        return UserSerializer(instance.created_by, read_only=True).data

    def get_image_url(self, instance):
        if not instance.image:
            return None

        return default_storage.url(instance.image)

    def get_is_removed(self, instance):
        unified_document = instance.unified_document
        return unified_document.is_removed

    def get_note(self, instance):
        from note.serializers import NoteSerializer

        note = instance.note
        if note:
            return NoteSerializer(instance.note, context=self.context).data
        return None

    def get_unified_document_id(self, instance):
        unified_document = instance.unified_document
        return instance.unified_document.id if unified_document is not None else None

    def get_unified_document(self, obj):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        serializer = DynamicUnifiedDocumentSerializer(
            obj.unified_document,
            _include_fields=[
                "id",
                "reviews",
                "title",
                "documents",
                "slug",
                "is_removed",
                "is_public",
                "document_type",
                "created_by",
            ],
            context={
                # Thread the request through so the nested post-visibility
                # guard (DynamicPostSerializer.to_representation) evaluates the
                # actual viewer instead of treating the request as anonymous.
                "request": self.context.get("request"),
                "doc_duds_get_created_by": {
                    "_include_fields": [
                        "id",
                        "author_profile",
                    ]
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                },
                "doc_duds_get_documents": {
                    "_include_fields": [
                        "id",
                        "title",
                        "slug",
                        "paper_title",
                    ]
                },
            },
            many=False,
        )

        return serializer.data

    def get_full_markdown(self, instance):
        try:
            if instance.document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                byte_string = instance.discussion_src.read()
            else:
                byte_string = instance.eln_src.read()
            full_markdown = byte_string.decode("utf-8")
            return full_markdown
        except Exception:
            logger.exception("Error getting full markdown for document")
            return None

    def get_hubs(self, instance):
        return SimpleHubSerializer(instance.unified_document.hubs, many=True).data

    def get_grants(self, post):
        if post.document_type != PREREGISTRATION:
            return []

        unified_document = post.unified_document
        if unified_document is None:
            return []

        reviews_by_grant_id = {}
        prefetched_reviews = getattr(
            unified_document, "_prefetched_objects_cache", {}
        ).get("proposal_reviews")
        if prefetched_reviews is not None:
            for review in prefetched_reviews:
                if review.grant_id is not None:
                    reviews_by_grant_id[review.grant_id] = review
        else:
            for review in ProposalReview.objects.filter(
                unified_document=unified_document,
                grant__isnull=False,
            ):
                reviews_by_grant_id[review.grant_id] = review

        ud_id = unified_document.id
        applications = list(post.grant_applications.all())
        grant_ids = {app.grant_id for app in applications}

        grant_post_by_ud = {}
        for p in ResearchhubPost.objects.filter(
            unified_document_id__in={
                app.grant.unified_document_id for app in applications
            }
        ).order_by("id"):
            grant_post_by_ud.setdefault(p.unified_document_id, p)
        applicant_counts = (
            dict(
                GrantApplication.objects.with_approved_proposal()
                .filter(grant_id__in=grant_ids)
                .values_list("grant_id")
                .annotate(count=Count("id"))
            )
            if grant_ids
            else {}
        )

        out = []
        for application in applications:
            grant = application.grant
            review = reviews_by_grant_id.get(grant.id)
            ai_peer_review = (
                ProposalReviewSerializer(review, context=self.context).data
                if review is not None
                else None
            )

            grant_post = grant_post_by_ud.get(grant.unified_document_id)
            out.append(
                {
                    "id": grant.id,
                    "short_title": grant.short_title,
                    "status": grant.status,
                    "organization": grant.organization,
                    "amount": str(grant.amount),
                    "currency": grant.currency,
                    "post_id": grant_post.id if grant_post else None,
                    "image_url": self._get_grant_image(grant_post),
                    "title": grant_post.title if grant_post else None,
                    "applicant_count": applicant_counts.get(grant.id, 0),
                    "application_visibility": grant.application_visibility,
                    "proposal": {
                        "unified_document_id": ud_id,
                        "ai_peer_review": ai_peer_review,
                    },
                }
            )
        return out

    @staticmethod
    def _get_grant_image(grant_post):
        if grant_post and grant_post.image:
            return default_storage.url(grant_post.image)
        return None

    def get_peer_reviews(self, instance):
        from review.models import Review

        unified_document = instance.unified_document
        if not unified_document:
            return []

        reviews = Review.objects.filter(
            unified_document=unified_document,
            is_removed=False,
        )
        serializer = DynamicReviewSerializer(
            reviews,
            many=True,
            _include_fields=[
                "id",
                "score",
                "is_assessed",
                "created_by",
                "created_date",
                "updated_date",
            ],
            context={
                "rev_drs_get_created_by": {
                    "_include_fields": [
                        "id",
                        "author_profile",
                        "first_name",
                        "last_name",
                    ]
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                },
            },
        )
        return serializer.data

    def get_promoted_score(self, instance):
        return instance.get_promoted_score()

    def get_boost_amount(self, instance):
        return instance.get_boost_amount()


class DynamicPostSerializer(
    DynamicModelFieldSerializer, ModeratedDocumentStatusSerializerMixin
):
    authors = SerializerMethodField()
    boost_amount = SerializerMethodField()
    bounties = SerializerMethodField()
    created_by = SerializerMethodField()
    discussions = SerializerMethodField()
    discussion_aggregates = SerializerMethodField()
    hubs = SerializerMethodField()
    note = SerializerMethodField()
    peer_reviews = SerializerMethodField()
    purchases = SerializerMethodField()
    score = SerializerMethodField()
    unified_document = SerializerMethodField()
    unified_document_id = SerializerMethodField()
    user_vote = SerializerMethodField()
    image_url = SerializerMethodField()

    class Meta:
        model = ResearchhubPost
        fields = "__all__"

    def to_representation(self, instance):
        """Redact private posts for viewers who are not allowed to see them.

        ``DynamicPostSerializer`` is the shared chokepoint through which post
        content is embedded in other resources (unified documents, comment
        threads, notifications, reviews, bounties, activity feeds). Guarding it
        here ensures a private preregistration's content never leaks via any of
        those paths to an unauthorized viewer.
        """
        unified_document = instance.unified_document
        if unified_document is not None and not (
            unified_document.is_public and unified_document.is_approved
        ):
            user = get_user_from_request(self.context)
            if not unified_document.is_visible_to_user(user):
                return {"id": instance.id, "is_public": False}
        return super().to_representation(instance)

    def get_authors(self, post):
        context = self.context
        _context_fields = {
            "_include_fields": [
                "id",
                "first_name",
                "last_name",
                "user",
            ]
        }
        serializer = DynamicAuthorSerializer(
            post.authors, context=context, many=True, **_context_fields
        )
        return serializer.data

    def get_bounties(self, post):
        from reputation.serializers import DynamicBountySerializer

        context = self.context
        _context_fields = context.get("doc_dps_get_bounties", {})
        _select_related_fields = context.get("doc_dps_get_bounties_select", [])
        _prefetch_related_fields = context.get("doc_dps_get_bounties_prefetch", [])
        bounties = (
            post.unified_document.related_bounties.select_related(
                *_select_related_fields
            )
            .prefetch_related(*_prefetch_related_fields)
            .all()
        )
        serializer = DynamicBountySerializer(
            bounties,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_discussions(self, post):
        from researchhub_comment.serializers import DynamicRhThreadSerializer

        context = self.context
        _context_fields = context.get("doc_dps_get_discussions", {})
        _select_related_fields = context.get("doc_dps_get_discussions_select", [])
        _prefetch_related_fields = context.get("doc_dps_get_discussions_prefetch", [])
        serializer = DynamicRhThreadSerializer(
            post.rh_threads.select_related(*_select_related_fields).prefetch_related(
                *_prefetch_related_fields
            ),
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_discussion_aggregates(self, post):
        return post.rh_threads.get_discussion_aggregates(post)

    def get_note(self, post):
        from note.serializers import DynamicNoteSerializer

        context = self.context
        _context_fields = context.get("doc_dps_get_note", {})
        serializer = DynamicNoteSerializer(
            post.note, context=context, **_context_fields
        )
        return serializer.data

    def get_peer_reviews(self, post):
        from review.models import Review

        context = self.context
        _context_fields = context.get("doc_dps_get_peer_reviews", {})
        unified_document = post.unified_document
        if not unified_document:
            return []

        reviews = Review.objects.filter(
            unified_document=unified_document,
            is_removed=False,
        )
        serializer = DynamicReviewSerializer(
            reviews,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_unified_document(self, post):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        context = self.context
        _context_fields = context.get("doc_dps_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            post.unified_document, context=context, **_context_fields
        )
        return serializer.data

    def get_unified_document_id(self, post):
        unified_document = post.unified_document
        return unified_document.id if unified_document is not None else None

    def get_hubs(self, post):
        context = self.context
        _context_fields = context.get("doc_dps_get_hubs", {})
        serializer = DynamicHubSerializer(
            post.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_created_by(self, post):
        context = self.context
        _context_fields = context.get("doc_dps_get_created_by", {})
        serializer = DynamicUserSerializer(
            post.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_purchases(self, post):
        from purchase.serializers import DynamicPurchaseSerializer

        context = self.context
        _context_fields = context.get("doc_dps_get_purchases", {})
        _select_related_fields = context.get("doc_dps_get_purchases_select", [])
        _prefetch_related_fields = context.get("doc_dps_get_purchases_prefetch", [])
        serializer = DynamicPurchaseSerializer(
            post.purchases.filter(purchase_type=Purchase.BOOST)
            .select_related(*_select_related_fields)
            .prefetch_related(*_prefetch_related_fields),
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_boost_amount(self, post):
        if post.purchases.exists():
            return post.get_boost_amount()
        return 0

    def get_score(self, post):
        return post.unified_document.score

    def get_user_vote(self, post):
        vote = None
        user = get_user_from_request(self.context)
        _context_fields = self.context.get("doc_dps_get_user_vote", {})
        try:
            if user and not user.is_anonymous:
                vote = post.votes.get(created_by=user)
                vote = DynamicVoteSerializer(
                    vote,
                    context=self.context,
                    **_context_fields,
                ).data
            return vote
        except Vote.DoesNotExist:
            return None

    def get_image_url(self, post):
        if not post.image:
            return None

        return default_storage.url(post.image)
