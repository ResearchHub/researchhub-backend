from datetime import datetime

import rest_framework.serializers as serializers
from django.db import transaction
from django.utils.text import slugify
from jsonschema import validate
from rest_framework.serializers import (
    JSONField,
    ReadOnlyField,
    SerializerMethodField,
    ValidationError,
)

from citation.constants import ZOTERO_TO_CSL_MAPPING
from citation.related_models.citation_entry_model import CitationEntry
from citation.schema import CSL_SCHEMA, generate_schema_for_citation
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import DynamicOrganizationSerializer, DynamicUserSerializer
from utils.http import remove_origin_from_url
from utils.serializers import DefaultAuthenticatedSerializer


class MinimalCitationEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CitationEntry
        fields = [
            "id",
            "organization_id",
            "project_id",
            "related_unified_doc_id",
        ]


class CitationEntrySerializer(DefaultAuthenticatedSerializer):
    checksum = ReadOnlyField()
    fields = JSONField()
    required_fields = SerializerMethodField(read_only=True)
    related_unified_doc = SerializerMethodField()

    class Meta:
        model = CitationEntry
        fields = "__all__"

    """ ----- Django Method Overrides -----"""

    def create(self, validated_data):
        from citation.utils import get_paper_by_doi

        with transaction.atomic():
            cleaned_attachment, attachment_name = self._get_cleaned_up_attachment(
                validated_data
            )
            try:
                if doi := validated_data.get("doi", None):
                    paper = get_paper_by_doi(doi)
                    validated_data["related_unified_doc_id"] = paper.unified_document.id
            except Exception:
                pass

            citation_entry = self._add_attachment(
                citation_entry=super().create(validated_data),
                attachment=cleaned_attachment,
                attachment_name=attachment_name,
            )
            custom_fields = citation_entry.fields.get("custom")
            if custom_fields:
                pdf_url = custom_fields.get("attachment")
                if pdf_url and "uploads/citation_entry/attachment" in pdf_url:
                    pdf_without_query_string = pdf_url.split("?")[0]
                    citation_entry.attachment = remove_origin_from_url(
                        pdf_without_query_string
                    )
                    citation_entry.save()
            from citation.utils import create_paper_from_citation

            create_paper_from_citation(citation_entry)
            return citation_entry

    def update(self, instance, validated_data):
        entry = super().update(instance, validated_data)
        with transaction.atomic():
            cleaned_attachment, attachment_name = self._get_cleaned_up_attachment(
                validated_data
            )
            citation_entry = self._add_attachment(
                citation_entry=entry,
                attachment=cleaned_attachment,
                attachment_name=attachment_name,
            )
            citation_entry.updated_date = datetime.now()
            citation_entry.save()
            return citation_entry

    def validate_fields(self, fields_data):
        citation_type = self.initial_data.get("citation_type")
        self._attach_csl_type(citation_type, fields_data)
        self._attach_csl_id(citation_type, fields_data)
        if not citation_type:
            raise ValidationError("No citation type provided")
        # validate([fields_data], schema=CSL_SCHEMA)

        return fields_data

    """ ----- Serializer Methods -----"""

    def _attach_csl_type(self, citation_type, fields_data):
        fields_data["type"] = ZOTERO_TO_CSL_MAPPING[citation_type]

    def _attach_csl_id(self, citation_type, fields_data):
        request = self.context.get("request")
        user = request.user
        fields_data["id"] = f"user_{user.id}_{citation_type}"

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

    def get_related_unified_doc(self, citation_entry):
        related_unified_doc = citation_entry.related_unified_doc
        if related_unified_doc:
            serializer = DynamicUnifiedDocumentSerializer(
                related_unified_doc,
                _include_fields=[
                    "id",
                    "documents",
                    "paper_title",
                    "document_type",
                ],
                context={
                    "doc_duds_get_documents": {
                        "_include_fields": [
                            "id",
                            "file",
                            "title",
                            "slug",
                            "paper_title",
                        ]
                    },
                },
                many=False,
            )
            return serializer.data
        return None

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
    related_unified_doc = SerializerMethodField()
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

    def get_related_unified_doc(self, citation_entry):
        related_unified_doc = citation_entry.related_unified_doc
        if related_unified_doc:
            serializer = DynamicUnifiedDocumentSerializer(
                related_unified_doc,
                _include_fields=[
                    "id",
                    "documents",
                    "paper_title",
                    "document_type",
                ],
                context={
                    "doc_duds_get_documents": {
                        "_include_fields": [
                            "id",
                            "title",
                            "slug",
                            "paper_title",
                        ]
                    },
                },
                many=False,
            )
            return serializer.data

    def get_organization(self, citation):
        context = self.context
        _context_fields = context.get("cit_dcs_get_organization", {})
        serializer = DynamicOrganizationSerializer(
            citation.organization, context=context, **_context_fields
        )
        return serializer.data
