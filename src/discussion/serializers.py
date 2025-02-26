import rest_framework.serializers as serializers
from django.contrib.contenttypes.models import ContentType

# TODO: Make is_public editable for creator as a delete mechanism
# TODO: undo
from django.db.models import Count, Q, Sum

from discussion.models import Reply, Thread
from discussion.reaction_models import Vote
from discussion.reaction_serializers import (
    DynamicVoteSerializer,  # Import is needed for discussion serializer imports
)
from discussion.reaction_serializers import (
    Flag,
    GenericReactionSerializerMixin,
    VoteSerializer,
)
from hub.serializers import DynamicHubSerializer
from paper.models import Paper
from reputation.models import Escrow
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from review.serializers.review_serializer import (
    DynamicReviewSerializer,
    ReviewSerializer,
)
from user.serializers import (
    DynamicUserSerializer,
    DynamicVerdictSerializer,
    MinimalUserSerializer,
)
from utils.http import get_user_from_request

ORDERING_SCORE_ANNOTATION = Count("id", filter=Q(votes__vote_type=Vote.UPVOTE)) - Count(
    "id", filter=Q(votes__vote_type=Vote.DOWNVOTE)
)


class CensorMixin:
    def get_plain_text(self, obj):
        return self.censor_unless_moderator(obj, obj.plain_text)

    def get_title(self, obj):
        return self.censor_unless_moderator(obj, obj.title)

    def get_text(self, obj):
        return self.censor_unless_moderator(obj, obj.text)

    def censor_unless_moderator(self, obj, value):
        if not obj.is_removed or self.requester_is_moderator():
            return value
        else:
            if type(value) == str:
                return "[{} has been removed]".format(obj._meta.model_name)
            else:
                return None

    def requester_is_moderator(self):
        request = self.context.get("request")
        return (
            request
            and request.user
            and request.user.is_authenticated
            and request.user.moderator
        )


class DynamicThreadSerializer(
    DynamicModelFieldSerializer,
    GenericReactionSerializerMixin,
):
    bounties = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    discussion_type = serializers.SerializerMethodField()
    is_accepted_answer = serializers.ReadOnlyField()
    is_created_by_editor = serializers.BooleanField(
        required=False,
    )
    paper = serializers.SerializerMethodField()
    post = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()  # @property
    unified_document = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    awarded_bounty_amount = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = "__all__"

    def get_discussion_type(self, obj):
        return Thread.__name__

    def _comments_query(self, obj):
        filter_by_user_id = self.context.get("_config", {}).get(
            "filter_by_user_id", None
        )

        if filter_by_user_id:
            replies = Reply.objects.filter(created_by_id=filter_by_user_id)
            comments = obj.children.filter(is_removed=False).filter(
                Q(id__in=[r.object_id for r in replies])
                | Q(created_by_id=filter_by_user_id)
            )
        else:
            comments = obj.children

        return comments.annotate(ordering_score=ORDERING_SCORE_ANNOTATION).order_by(
            "-ordering_score", "created_date"
        )

    def get_awarded_bounty_amount(self, thread):
        amount_awarded = None
        bounty_solution = thread.bounty_solution.first()

        if bounty_solution:
            uni_doc_content_type = ContentType.objects.get_for_model(
                ResearchhubUnifiedDocument
            )

            awarded_escrow = Escrow.objects.filter(
                object_id=thread.unified_document.id,
                content_type=uni_doc_content_type,
            )
            amount_awarded = awarded_escrow.aggregate(Sum("amount_paid")).get(
                "amount_paid__sum", None
            )

        return amount_awarded

    def get_bounties(self, obj):
        from reputation.serializers import DynamicBountySerializer

        context = self.context
        _context_fields = context.get("dis_dts_get_bounties", {})
        serializer = DynamicBountySerializer(
            obj.bounties.all(), many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        _context_fields = self.context.get("dis_dcs_get_user_vote", {})
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by=user)
            if vote.exists():
                return DynamicVoteSerializer(
                    vote.last(),
                    context=self.context,
                    **_context_fields,
                ).data
            return False
        return False

    def get_created_by(self, thread):
        context = self.context
        _context_fields = context.get("dis_dts_get_created_by", {})
        serializer = DynamicUserSerializer(
            thread.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_comment_count(self, obj):
        return self._comments_query(obj).count()

    def get_paper(self, thread):
        from paper.serializers import DynamicPaperSerializer

        paper = thread.paper
        if not paper:
            return None

        context = self.context
        _context_fields = context.get("dis_dts_get_paper", {})

        serializer = DynamicPaperSerializer(paper, context=context, **_context_fields)
        return serializer.data

    def get_post(self, thread):
        from researchhub_document.serializers import DynamicPostSerializer

        post = thread.post
        if not post:
            return None

        context = self.context
        _context_fields = context.get("dis_dts_get_post", {})
        serializer = DynamicPostSerializer(
            thread.post, context=context, **_context_fields
        )
        return serializer.data

    def get_review(self, obj):
        if obj.review:
            context = self.context
            _context_fields = context.get("dis_dts_get_review", {})

            serializer = DynamicReviewSerializer(
                obj.review, context=context, **_context_fields
            )

            return serializer.data

        return None

    def get_score(self, obj):
        return obj.calculate_score()

    def get_unified_document(self, thread):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        context = self.context
        _context_fields = context.get("dis_dts_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            thread.unified_document, context=context, **_context_fields
        )
        return serializer.data


class ThreadSerializer(serializers.ModelSerializer, GenericReactionSerializerMixin):
    awarded_bounty_amount = serializers.SerializerMethodField()
    bounties = serializers.SerializerMethodField()
    created_by = MinimalUserSerializer(
        read_only=False, default=serializers.CurrentUserDefault()
    )
    comment_count = serializers.SerializerMethodField()
    document_meta = serializers.SerializerMethodField()
    is_created_by_editor = serializers.BooleanField(required=False, read_only=True)
    paper_slug = serializers.SerializerMethodField()
    post_slug = serializers.SerializerMethodField()
    promoted = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()  # @property
    unified_document = serializers.SerializerMethodField()
    user_flag = serializers.SerializerMethodField()

    class Meta:
        fields = [
            "awarded_bounty_amount",
            "block_key",
            "bounties",
            "citation",
            "comment_count",
            "context_title",
            "created_by",
            "created_date",
            "created_location",
            "discussion_post_type",
            "document_meta",
            "entity_key",
            "external_metadata",
            "id",
            "is_accepted_answer",
            "is_created_by_editor",
            "is_public",
            "is_removed",
            "paper_slug",
            "paper",
            "plain_text",
            "post_slug",
            "post",
            "promoted",
            "review",
            "score",
            "source",
            "text",
            "title",
            "unified_document",
            "user_flag",
            "was_edited",
        ]
        read_only_fields = [
            "awarded_bounty_amount",
            "document_meta",
            "document_meta",
            "is_accepted_answer",
            "is_created_by_editor",
            "is_public",
            "is_removed",
            "score",
            "user_flag",
        ]
        model = Thread

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by=user)
            if vote.exists():
                return VoteSerializer(vote.last()).data
            return False
        return False

    def _comments_query(self, obj):
        return (
            obj.children.filter(is_removed=False)
            .annotate(ordering_score=ORDERING_SCORE_ANNOTATION)
            .order_by("-ordering_score", "created_date")
        )

    def get_comment_count(self, obj):
        return self._comments_query(obj).count()

    def get_paper_slug(self, obj):
        if obj.paper:
            return obj.paper.slug

    def get_post_slug(self, obj):
        if obj.post:
            return obj.post.slug

    def get_review(self, obj):
        if obj.review:
            return ReviewSerializer(obj.review).data

        return None

    def get_unified_document(self, obj):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        serializer = DynamicUnifiedDocumentSerializer(
            obj.unified_document,
            _include_fields=["id", "reviews"],
            context={},
            many=False,
        )

        return serializer.data

    def get_bounties(self, obj):
        from reputation.serializers import DynamicBountySerializer

        context = {
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile",)},
            "rep_dbs_get_solution": {"_include_fields": ("id",)},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "profile_image",
                    "first_name",
                    "last_name",
                )
            },
        }

        serializer = DynamicBountySerializer(
            obj.bounties.all(),
            many=True,
            context=context,
            _include_fields=(
                "item_object_id",
                "id",
                "status",
                "created_by",
                "amount",
                "created_date",
                "expiration_date",
            ),
        )
        return serializer.data

    def get_awarded_bounty_amount(self, obj):
        amount_awarded = None
        bounty_solution = obj.bounty_solution.first()

        if bounty_solution:
            bounty = bounty_solution.bounty
            content_type = ContentType.objects.get_for_model(obj.unified_document)
            amount_awarded = (
                Escrow.objects.filter(
                    object_id=obj.unified_document.id,
                    content_type=content_type,
                )
                .aggregate(Sum("amount_paid"))
                .get("amount_paid__sum", None)
            )

        return amount_awarded

    def get_score(self, obj):
        return obj.calculate_score()


class SimpleThreadSerializer(ThreadSerializer):
    class Meta:
        fields = [
            "id",
        ]
        model = Thread


class DynamicFlagSerializer(DynamicModelFieldSerializer):
    item = serializers.SerializerMethodField()
    flagged_by = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    verdict = serializers.SerializerMethodField()

    class Meta:
        model = Flag
        fields = "__all__"

    def get_item(self, flag):
        context = self.context
        _context_fields = context.get("dis_dfs_get_item", {})
        item = flag.item

        if isinstance(item, Paper):
            from paper.serializers import DynamicPaperSerializer

            serializer = DynamicPaperSerializer
        elif isinstance(item, ResearchhubPost):
            from researchhub_document.serializers import DynamicPostSerializer

            serializer = DynamicPostSerializer
        elif isinstance(item, RhCommentModel):
            from researchhub_comment.serializers import DynamicRhCommentSerializer

            serializer = DynamicRhCommentSerializer
        else:
            return None
        data = serializer(item, context=context, **_context_fields).data

        return data

    def get_flagged_by(self, flag):
        context = self.context
        _context_fields = context.get("dis_dfs_get_created_by", {})
        serializer = DynamicUserSerializer(
            flag.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, flag):
        content_type = flag.content_type
        return {"id": content_type.id, "name": content_type.model}

    def get_hubs(self, flag):
        context = self.context
        _context_fields = context.get("dis_dfs_get_hubs", {})
        serializer = DynamicHubSerializer(
            flag.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_verdict(self, flag):
        context = self.context
        verdict = getattr(flag, "verdict", None)

        if not verdict:
            return None

        _context_fields = context.get("dis_dfs_get_verdict", {})
        serializer = DynamicVerdictSerializer(
            verdict, context=context, **_context_fields
        )
        return serializer.data
