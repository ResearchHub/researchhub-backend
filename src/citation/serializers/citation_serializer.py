import rest_framework.serializers as serializers
from jsonschema import validate
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from citation.models import CitationEntry
from citation.schema import generate_schema_for_citation
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicOrganizationSerializer, DynamicUserSerializer


class CitationSerializer(ModelSerializer):
    checksum = serializers.ReadOnlyField()
    fields = serializers.JSONField()

    class Meta:
        model = CitationEntry
        fields = "__all__"

    def validate_fields(self, data):
        initial_data = self.initial_data
        citation_type = initial_data.get("citation_type")
        if not citation_type:
            raise serializers.ValidationError("No citation type provided")
        schema = generate_schema_for_citation(citation_type)
        validate(data, schema=schema)
        return data


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
