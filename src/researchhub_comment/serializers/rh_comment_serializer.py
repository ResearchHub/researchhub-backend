from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from rest_framework.serializers import SerializerMethodField

from discussion.reaction_serializers import (
    GenericReactionSerializer,
    GenericReactionSerializerMixin,
)
from purchase.serializers import DynamicPurchaseSerializer
from reputation.models import Escrow
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_comment.serializers.constants.rh_comment_serializer_contants import (
    RH_COMMENT_FIELDS,
    RH_COMMENT_READ_ONLY_FIELDS,
)
from user.serializers import DynamicUserSerializer


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
    created_by = SerializerMethodField()
    thread = SerializerMethodField()
    children_count = SerializerMethodField()
    children = SerializerMethodField()
    purchases = SerializerMethodField()
    bounties = SerializerMethodField()
    awarded_bounty_amount = SerializerMethodField()

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
        view = context["view"]
        thread = comment.thread
        depth_key = f"rhc_dcs_get_children_{thread.id}_depth"
        relative_depth_key = f"relative_depth_{comment.id}"
        _context_fields = context.get("rhc_dcs_get_children", {})
        max_depth = context.get("rhc_dcs_get_children_max_depth", 3)
        depth_context = context.get(depth_key, {})
        thread_depth = depth_context.get("thread_depth", None)

        print(comment.id, thread_depth)
        if not thread_depth:
            thread_depth = 1
            context[depth_key] = {"thread_depth": 1, relative_depth_key: 1}
        if thread_depth >= max_depth:
            return []

        if parent := comment.parent:
            parent_key = f"relative_depth_{parent.id}"
            if parent_key in depth_context:
                depth_context[relative_depth_key] = depth_context[parent_key] + 1
            else:
                depth_context[parent_key] = 1
                depth_context[relative_depth_key] = depth_context[parent_key]

            if depth_context[relative_depth_key] >= max_depth:
                return []

        # Passing comment.children as a related manager for filtering purposes
        # See filter class for more details
        serializer = DynamicRhCommentSerializer(
            view.filter_queryset(comment.children),
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
