from django.core.files.storage import default_storage
from rest_framework.serializers import CharField, ModelSerializer, SerializerMethodField

from ai_peer_review.models import ProposalReview
from ai_peer_review.serializers import ProposalReviewSerializer
from discussion.models import Vote
from discussion.serializers import (
    DynamicVoteSerializer,  # Import is needed for discussion serializer imports
)
from discussion.serializers import GenericReactionSerializerMixin
from hub.serializers import DynamicHubSerializer, SimpleHubSerializer
from purchase.models import Purchase
from researchhub.serializers import DynamicModelFieldSerializer
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


class ResearchhubPostSerializer(ModelSerializer, GenericReactionSerializerMixin):
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
            "slug",
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
            return NoteSerializer(instance.note).data
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
                "document_type",
                "created_by",
            ],
            context={
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
        except Exception as e:
            print(e)
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
        out = []
        for application in post.grant_applications.all():
            grant = application.grant
            review = reviews_by_grant_id.get(grant.id)
            ai_peer_review = (
                ProposalReviewSerializer(review, context=self.context).data
                if review is not None
                else None
            )

            grant_post = None
            grant_posts = grant.unified_document.posts.all()
            if grant_posts:
                grant_post = grant_posts[0]

            grant_image_url = None
            if grant_post and grant_post.image:
                grant_image_url = default_storage.url(grant_post.image)

            out.append(
                {
                    "id": grant.id,
                    "short_title": grant.short_title,
                    "status": grant.status,
                    "organization": grant.organization,
                    "amount": str(grant.amount),
                    "currency": grant.currency,
                    "post_id": grant_post.id if grant_post else None,
                    "image_url": grant_image_url,
                    "title": grant_post.title if grant_post else None,
                    "applicant_count": grant.applications.count(),
                    "proposal": {
                        "unified_document_id": ud_id,
                        "ai_peer_review": ai_peer_review,
                    },
                }
            )
        return out

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


class DynamicPostSerializer(DynamicModelFieldSerializer):
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
