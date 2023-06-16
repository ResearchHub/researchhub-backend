from datetime import datetime

from django.db import transaction
from django.utils.text import slugify
from jsonschema import validate
from rest_framework.serializers import (
    JSONField,
    ReadOnlyField,
    SerializerMethodField,
    ValidationError,
)

from citation.related_models.citation_entry_model import CitationEntry
from citation.schema import generate_schema_for_citation
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicOrganizationSerializer, DynamicUserSerializer
from utils.serializers import DefaultAuthenticatedSerializer


class CitationEntrySerializer(DefaultAuthenticatedSerializer):
    checksum = ReadOnlyField()
    fields = JSONField()
    required_fields = SerializerMethodField(read_only=True)

    class Meta:
        model = CitationEntry
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    def create(self, validated_data):
        with transaction.atomic():
            cleaned_attachment, attachment_name = self._get_cleaned_up_attachment(
                validated_data
            )
            citation_entry = self._add_attachment(
                citation_entry=super().create(validated_data),
                attachment=cleaned_attachment,
                attachment_name=attachment_name,
            )
            return citation_entry

    def update(self, instance, validated_data):
        with transaction.atomic():
            cleaned_attachment, attachment_name = self._get_cleaned_up_attachment(
                validated_data
            )
            citation_entry = self._add_attachment(
                citation_entry=super().update(instance, validated_data),
                attachment=cleaned_attachment,
                attachment_name=attachment_name,
            )
            citation_entry.updated_date = datetime.now()
            citation_entry.save()
            return citation_entry

    def validate_fields(self, fields_data):
        citation_type = self.initial_data.get("citation_type")
        if not citation_type:
            raise ValidationError("No citation type provided")
        schema = generate_schema_for_citation(citation_type)
        validate(fields_data, schema=schema)

        return fields_data

    """ ----- Serializer Methods -----"""

    def get_attachment_url(self, citation_entry):
        try:
            attachment = citation_entry.attachment
            if attachment is None:
                return None
            return attachment.url
        except Exception as error:
            return None

    def get_required_fields(self, citation_entry):
        return (
            generate_schema_for_citation(
                citation_type=citation_entry.citation_type
            ).get("required")
            or []
        )

    """ ----- Private Methods -----"""

    def _get_cleaned_up_attachment(self, validated_data):
        if validated_data.get("attachment", None) is None:
            return [None, None]

        attachment = validated_data.pop("attachment")
        content_type = attachment.name.split(".")[-1]
        return [
            attachment,
            f"{slugify(attachment.name)}.{content_type}",
        ]

    def _add_attachment(self, citation_entry, attachment, attachment_name):
        if attachment is not None:
            citation_entry.attachment.save(
                attachment_name,
                attachment,
            )
        return citation_entry


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
