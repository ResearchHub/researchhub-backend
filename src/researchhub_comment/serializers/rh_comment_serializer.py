from rest_framework.serializers import SerializerMethodField

from discussion.reaction_serializers import (
    GenericReactionSerializer,
    GenericReactionSerializerMixin,
)
from purchase.serializers import DynamicPurchaseSerializer
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
        depth_key = f"rhc_dcs_get_children_{comment.thread.id}_depth"
        _context_fields = context.get("rhc_dcs_get_children", {})
        depth = context.get(depth_key, None)
        max_depth = context.get("rhc_dcs_get_children_max_depth", 3)

        if not depth:
            depth = 1
            context[depth_key] = depth
        if depth >= max_depth:
            return []

        context[depth_key] += 1
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


"""
from researchhub_comment.serializers import DynamicRhCommentSerializer

x = DynamicRhCommentSerializer(RhCommentModel.objects.last(), _include_fields=("id", "created_by"), context={"rhc_dcs_get_created_by": {"_include_fields":("id",)}})
x.data
"""
