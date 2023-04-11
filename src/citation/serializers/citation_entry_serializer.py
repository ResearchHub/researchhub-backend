from django.core.files.base import ContentFile
from jsonschema import validate
from rest_framework.serializers import (
    JSONField,
    ModelSerializer,
    ReadOnlyField,
    SerializerMethodField,
    ValidationError,
)
from django.db import transaction

from citation.related_models.citation_entry import CitationEntry
from citation.schema import generate_schema_for_citation
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicOrganizationSerializer, DynamicUserSerializer


class CitationEntrySerializer(ModelSerializer):
    attachment_url = SerializerMethodField(read_only=True)
    checksum = ReadOnlyField()
    fields = JSONField()
    required_fields = SerializerMethodField(read_only=True)

    class Meta:
        model = CitationEntry
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    def create(self, validated_data):
        with transaction.atomic():
            [attachment_name, cleaned_attachment] = self._get_cleaned_up_attachment()
            citation_entry = super().create(validated_data)
            if cleaned_attachment is not None:
                citation_entry.attachment.save(
                    attachment_name,
                    cleaned_attachment,
                )
            return citation_entry

    def validate_fields(self, fields_data):
        citation_type = self.initial_data.get("citation_type")
        if not citation_type:
            raise ValidationError("No citation type provided")
        schema = generate_schema_for_citation(citation_type)
        validate(fields_data, schema=schema)
        fields_data["attachment"] = self.initial_data.get("attachment")
        fields_data["file"] = self.initial_data.get("attachment")

        return fields_data

    """ ----- Serializer Methods -----"""

    def get_attachment_url(self, citation_entry):
        attachment = citation_entry.attachment
        if attachment is None:
            return None
        return attachment.url

    def get_required_fields(self, citation_entry):
        return (
            generate_schema_for_citation(
                citation_type=citation_entry.citation_type
            ).get("required")
            or []
        )

    """ ----- Private Methods -----"""

    def _get_cleaned_up_attachment(self):
        initial_data = self.initial_data
        attachment_src = initial_data.get("attachment_src", None)
        if attachment_src is None:
            return None
        attachment_name = initial_data.get("attachment_name")
        return [
            attachment_name,
            ContentFile(attachment_src.encode(), name=f"{attachment_name}.pdf"),
        ]


class DynamicCitationEntrySerializer(DynamicModelFieldSerializer):
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
