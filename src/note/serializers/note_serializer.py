from rest_framework.serializers import ModelSerializer, SerializerMethodField

from note.models import Note, NoteContent
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
  DynamicUnifiedDocumentSerializer
)
from user.serializers import (
    DynamicOrganizationSerializer,
    DynamicUserSerializer
)


class NoteSerializer(ModelSerializer):
    class Meta:
        model = Note
        fields = '__all__'
        read_only_fields = ['unified_document']


class DynamicNoteSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    latest_version = SerializerMethodField()
    notes = SerializerMethodField()
    organization = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta:
        model = Note
        fields = '__all__'

    def get_created_by(self, note):
        context = self.context
        _context_fields = context.get('not_dns_get_created_by', {})
        serializer = DynamicUserSerializer(
            note.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_latest_version(self, note):
        context = self.context
        _context_fields = context.get('not_dns_get_latest_version', {})
        serializer = DynamicNoteContentSerializer(
            note.latest_version,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_notes(self, note):
        context = self.context
        _context_fields = context.get('not_dns_get_notes', {})
        serializer = DynamicNoteContentSerializer(
            note.notes,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_organization(self, note):
        context = self.context
        _context_fields = context.get('not_dns_get_organization', {})
        serializer = DynamicOrganizationSerializer(
            note.organization,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_unified_document(self, note):
        context = self.context
        _context_fields = context.get('not_dns_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            note.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data


class NoteContentSerializer(ModelSerializer):
    class Meta:
        model = NoteContent
        fields = '__all__'


class DynamicNoteContentSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = NoteContent
        fields = '__all__'
