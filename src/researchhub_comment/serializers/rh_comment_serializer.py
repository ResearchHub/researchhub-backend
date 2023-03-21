from rest_framework.serializers import IntegerField, SerializerMethodField

from discussion.reaction_serializers import (
    GenericReactionSerializer,
    GenericReactionSerializerMixin,
)
from discussion.serializers import GenericReactionSerializerMixin
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

    children = SerializerMethodField()

    def get_children(self, rh_comment):
        return RhCommentSerializer(
            instance=rh_comment.children,
            many=True,
        ).data


# TODO: Does generic reaction serializer mixin work?
class DynamicRhCommentSerializer(
    GenericReactionSerializerMixin, DynamicModelFieldSerializer
):
    created_by = SerializerMethodField()
    thread = SerializerMethodField()
    children = SerializerMethodField()

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

    def get_children(self, comment):
        context = self.context
        _context_fields = context.get("rhc_dcs_get_children", {})
        serializer = DynamicRhCommentSerializer(
            comment.children, many=True, context=context, **_context_fields
        )
        return serializer.data


"""
from researchhub_comment.serializers import DynamicRhCommentSerializer

x = DynamicRhCommentSerializer(RhCommentModel.objects.last(), _include_fields=("id", "created_by"), context={"rhc_dcs_get_created_by": {"_include_fields":("id",)}})
x.data
"""
