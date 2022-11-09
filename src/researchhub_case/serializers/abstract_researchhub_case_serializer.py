from rest_framework import serializers

from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_case.related_models.researchhub_case_abstract_model import (
    AbstractResearchhubCase,
)
from user.serializers import DynamicUserSerializer


class DynamicAbstractResearchhubCase(DynamicModelFieldSerializer):
    creator = serializers.SerializerMethodField()
    moderator = serializers.SerializerMethodField()
    requestor = serializers.SerializerMethodField()

    class Meta:
        model = AbstractResearchhubCase
        fields = "__all__"

    def get_creator(self, case):
        context = self.context
        _context_fields = context.get("cse_darc_get_creator", {})
        serializer = DynamicUserSerializer(
            case.creator, context=context, **_context_fields
        )
        return serializer.data

    def get_moderator(self, case):
        context = self.context
        _context_fields = context.get("cse_darc_get_moderator", {})
        serializer = DynamicUserSerializer(
            case.moderator, context=context, **_context_fields
        )
        return serializer.data

    def get_requestor(self, case):
        context = self.context
        _context_fields = context.get("cse_darc_get_requestor", {})
        serializer = DynamicUserSerializer(
            case.requestor, context=context, **_context_fields
        )
        return serializer.data
