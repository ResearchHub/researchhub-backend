from django.db.models import Sum
from rest_framework.serializers import SerializerMethodField

from discussion.models import Vote
from discussion.reaction_serializers import (
    GenericReactionSerializer,
    GenericReactionSerializerMixin,
    VoteSerializer,
)
from purchase.serializers import DynamicPurchaseSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_comment.serializers.constants.rh_comment_serializer_contants import (
    RH_COMMENT_FIELDS,
    RH_COMMENT_READ_ONLY_FIELDS,
)
from review.serializers.review_serializer import DynamicReviewSerializer
from user.serializers import DynamicUserSerializer
from utils.http import get_user_from_request


class RhCommentSerializer(GenericReactionSerializer):
    class Meta:
        model = RhCommentModel
        fields = [
            *GenericReactionSerializerMixin.EXPOSABLE_FIELDS,
            *RH_COMMENT_FIELDS,
        ]
        read_only_fields = [
            *GenericReactionSerializerMixin.READ_ONLY_FIELDS,
            *RH_COMMENT_READ_ONLY_FIELDS,
        ]

    children_count = SerializerMethodField()
    children = SerializerMethodField()

    def get_children_count(self, comment):
        return comment.children.count()

    def get_children(self, rh_comment):
        return RhCommentSerializer(
            instance=rh_comment.children,
            many=True,
        ).data


class DynamicRhCommentSerializer(
    GenericReactionSerializer,
    GenericReactionSerializerMixin,
    DynamicModelFieldSerializer,
):
    awarded_bounty_amount = SerializerMethodField()
    created_by = SerializerMethodField()
    thread = SerializerMethodField()
    children_count = SerializerMethodField()
    children = SerializerMethodField()
    purchases = SerializerMethodField()
    bounties = SerializerMethodField()
    user_vote = SerializerMethodField()
    review = SerializerMethodField()

    class Meta:
        fields = "__all__"
        model = RhCommentModel

    def get_created_by(self, comment):
        context = self.context
        _context_fields = context.get("rhc_dcs_get_created_by", {})
        serializer = DynamicUserSerializer(
            comment.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_thread(self, comment):
        from researchhub_comment.serializers import DynamicRhThreadSerializer

        context = self.context
        _context_fields = context.get("rhc_dcs_get_thread", {})
        serializer = DynamicRhThreadSerializer(
            comment.thread, context=context, **_context_fields
        )
        return serializer.data

    def get_children_count(self, comment):
        return comment.children.count()

    def get_children(self, comment):
        context = self.context
        # If the view key does not exist, ensure VIEWSET.get_serializer_context()
        # is called to properly to create the serializer context
        view = context.get("view", None)
        _context_fields = context.get("rhc_dcs_get_children", {})
        _filter_fields = _context_fields.get("_filter_fields", {})
        max_depth = context.get("rhc_dcs_get_children_max_depth", 3)
        depth_key = f"rhc_dcs_get_children_{comment.thread.id}_depth"
        relative_depth_key = f"relative_depth_{comment.id}"
        depth_context = context.get(depth_key, None)

        if not depth_context:
            depth_context = {}
            context[depth_key] = depth_context

        parent = comment.parent
        if relative_depth_key not in depth_context:
            parent_key = f"relative_depth_{parent.id}" if parent else None
            depth_context[relative_depth_key] = depth_context.get(parent_key, 0) + 1
        else:
            depth_context[relative_depth_key] += 1

        if depth_context[relative_depth_key] >= max_depth:
            return []

        # Passing comment.children as a related manager for filtering purposes
        # See filter class for more details
        if view:
            qs = view.filter_queryset(comment.children)
        else:
            qs = comment.children.filter(**_filter_fields)
        serializer = DynamicRhCommentSerializer(
            qs,
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_purchases(self, comment):
        context = self.context
        _context_fields = context.get("rhc_dcs_get_purchases", {})
        serializer = DynamicPurchaseSerializer(
            comment.purchases, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_bounties(self, comment):
        from reputation.serializers import DynamicBountySerializer

        context = self.context
        _context_fields = context.get("rhc_dcs_get_bounties", {})
        serializer = DynamicBountySerializer(
            comment.bounties.all(), many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_awarded_bounty_amount(self, comment):
        amount_awarded = None
        bounty_solution = comment.bounty_solution

        if not bounty_solution.exists():
            return None

        if bounty_solution := bounty_solution.first():
            bounty = bounty_solution.bounty
            escrow = bounty.escrow
            comment_creator = comment.created_by
            amount_awarded = (
                comment_creator.escrowrecipients_set.filter(escrow=escrow)
                .aggregate(Sum("amount"))
                .get("amount__sum", None)
            )

        return amount_awarded

    def get_user_vote(self, comment):
        vote = None
        user = get_user_from_request(self.context)
        try:
            if user and not user.is_anonymous:
                vote = comment.votes.get(created_by=user)
                vote = VoteSerializer(vote).data
            return vote
        except Vote.DoesNotExist:
            return None

        return None

    def get_review(self, comment):
        context = self.context
        _context_fields = context.get("rhc_dcs_get_review", {})
        review = comment.reviews.first()
        if review:
            serializer = DynamicReviewSerializer(
                review, many=False, context=context, **_context_fields
            )
            return serializer.data
