import rest_framework.serializers as serializers

# TODO: Make is_public editable for creator as a delete mechanism
# TODO: undo
from django.db.models import Count, Q

from discussion.reaction_models import Vote
from discussion.reaction_serializers import Flag
from hub.serializers import DynamicHubSerializer
from paper.models import Paper
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from user.serializers import DynamicUserSerializer, DynamicVerdictSerializer

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
