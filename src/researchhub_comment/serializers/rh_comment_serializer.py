from django.db.models import Sum
from rest_framework.serializers import SerializerMethodField

from discussion.models import Vote
from discussion.serializers import (
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

    best_score = SerializerMethodField()
    children_count = SerializerMethodField()
    children = SerializerMethodField()

    def get_best_score(self, comment):
        return getattr(comment, "best_score", None)

    def get_children_count(self, comment):
        return comment.children_count

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
    best_score = SerializerMethodField()
    created_by = SerializerMethodField()
    thread = SerializerMethodField()
    children_count = SerializerMethodField()
    children = SerializerMethodField()
    purchases = SerializerMethodField()
    bounties = SerializerMethodField()
    user_vote = SerializerMethodField()
    review = SerializerMethodField()
    parent = SerializerMethodField()

    class Meta:
        fields = "__all__"
        model = RhCommentModel

    def get_best_score(self, comment):
        return getattr(comment, "best_score", None)

    def get_parent(self, comment):
        context = self.context
        _context_fields = context.get("rhc_dcs_get_parent", {})

        if not comment.parent:
            return None

        serializer = DynamicRhCommentSerializer(
            comment.parent, context=context, **_context_fields
        )
        return serializer.data

    def get_created_by(self, comment):
        # For censored comments, don't expose the creator
        if comment.is_removed:
            return None

        context = self.context
        _context_fields = context.get("rhc_dcs_get_created_by", {})
        serializer = DynamicUserSerializer(
            comment.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_thread(self, comment):
        from researchhub_comment.serializers import DynamicRhThreadSerializer
        from researchhub_comment.serializers.utils import (
            create_thread_reference,
            increment_depth,
            should_use_reference_only,
        )

        context = self.context
        _context_fields = context.get("rhc_dcs_get_thread", {})

        # Use depth limiting to prevent circular dependencies
        if should_use_reference_only(context):
            return create_thread_reference(comment.thread)

        # Full serialization for shallow depths
        new_context = increment_depth(context)
        serializer = DynamicRhThreadSerializer(
            comment.thread, context=new_context, **_context_fields
        )
        return serializer.data

    def get_children_count(self, comment):
        return comment.children_count

    def get_children(self, comment):
        context = self.context
        # If the view key does not exist, ensure VIEWSET.get_serializer_context()
        # is called to properly to create the serializer context
        view = context.get("view", None)
        _context_fields = context.get("rhc_dcs_get_children", {})
        _filter_fields = _context_fields.get("_filter_fields", {})
        _select_related_fields = _context_fields.get("_select_related_fields", [])
        _prefetch_related_fields = _context_fields.get("_prefetch_related_fields", [])
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

        # Use all_objects instead of children to include removed (censored) comments
        # Passing comment.children as a related manager for filtering purposes
        # See filter class for more details
        # Build a queryset from all_objects that filters to this comment's children
        from researchhub_comment.models import RhCommentModel

        # Check if we have prefetched children (list) first
        if hasattr(comment, "prefetched_children"):
            # Use prefetched children which may include censored comments
            prefetched_children = comment.prefetched_children

            if isinstance(prefetched_children, list):
                # For lists, we can't use select_related/prefetch_related
                serializer = DynamicRhCommentSerializer(
                    prefetched_children,
                    many=True,
                    context=context,
                    **_context_fields,
                )
                return serializer.data
            else:
                # It's a queryset, proceed with normal select_related
                qs = prefetched_children
        elif view:
            # If view is available, use it to filter the queryset
            # But first we need to get all children from all_objects
            all_children = RhCommentModel.all_objects.filter(parent=comment)
            qs = view.filter_queryset(all_children)
        else:
            qs = RhCommentModel.all_objects.filter(parent=comment, **_filter_fields)

        serializer = DynamicRhCommentSerializer(
            qs.select_related(*_select_related_fields).prefetch_related(
                *_prefetch_related_fields
            ),
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
        
        # Use all() to access prefetched data, then check length
        # exists() always hits the database even with prefetch
        bounty_solution_list = bounty_solution.all()
        if not bounty_solution_list:
            return None

        if bounty_solution := bounty_solution_list[0]:
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
        reviews = comment.reviews
        # Use all() to access prefetched data instead of exists()
        reviews_list = reviews.all()
        if reviews_list:
            review = reviews_list[0]
            serializer = DynamicReviewSerializer(
                review, many=False, context=context, **_context_fields
            )
            return serializer.data

    def to_representation(self, instance):
        # Get the standard representation
        ret = super().to_representation(instance)

        # If the comment is censored, sanitize the content
        if instance.is_removed:
            ret["comment_content_json"] = {"ops": [{"insert": "[Comment removed]"}]}

        return ret
