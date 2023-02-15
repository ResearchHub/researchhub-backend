from rest_framework.serializers import ModelSerializer, SerializerMethodField

from citation.models import CitationEntry
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicOrganizationSerializer, DynamicUserSerializer


class CitationSerializer(ModelSerializer):
    class Meta:
        model = CitationEntry
        fields = "__all__"


class DynamicCitationSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    organization = SerializerMethodField()

    class Meta:
        model = CitationEntry
        fields = "__all__"

    def get_created_by(self, citation):
        context = self.context
        _context_fields = context.get("cit_dcs_get_created_by", {})
        serializer = DynamicUserSerializer(
            citation.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_organization(self, citation):
        context = self.context
        _context_fields = context.get("cit_dcs_get_organization", {})
        serializer = DynamicOrganizationSerializer(
            citation.organization, context=context, **_context_fields
        )
        return serializer.data
