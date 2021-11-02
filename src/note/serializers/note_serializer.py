from django.db.models import Q
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from note.models import Note, NoteContent
from researchhub_access_group.constants import (
    ADMIN,
    EDITOR,
    MEMBER,
    NO_ACCESS,
    PRIVATE,
    WORKSPACE,
    SHARED
)
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import (
  DynamicUnifiedDocumentSerializer
)
from user.serializers import (
    OrganizationSerializer,
    DynamicOrganizationSerializer,
    DynamicUserSerializer
)


class NoteContentSerializer(ModelSerializer):
    src = SerializerMethodField()

    class Meta:
        model = NoteContent
        fields = '__all__'

    def get_src(self, note_content):
        src = note_content.src
        if src:
            byte_string = note_content.src.read()
            data = byte_string.decode('utf-8')
            return data
        return None


class DynamicNoteContentSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = NoteContent
        fields = '__all__'


class NoteSerializer(ModelSerializer):
    latest_version = NoteContentSerializer()
    access = SerializerMethodField()
    organization = OrganizationSerializer()

    class Meta:
        model = Note
        fields = '__all__'
        read_only_fields = ['unified_document']

    def get_access(self, note):
        if hasattr(note, 'access'):
            return note.access
        return None


class DynamicNoteSerializer(DynamicModelFieldSerializer):
    access = SerializerMethodField()
    created_by = SerializerMethodField()
    latest_version = SerializerMethodField()
    notes = SerializerMethodField()
    organization = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta:
        model = Note
        fields = '__all__'

    def get_access(self, note):
        permissions = note.permissions

        is_workspace = permissions.filter(
            Q(access_type=ADMIN) &
            Q(user__isnull=True)
        ).exists()

        is_private = permissions.filter(
            Q(access_type__in=[ADMIN, MEMBER, EDITOR]) &
            Q(user__isnull=False)
        ).count() <= 1

        if is_workspace:
            return WORKSPACE
        elif is_private:
            return PRIVATE
        else:
            return SHARED

    def get_created_by(self, note):
        context = self.context
        _context_fields = context.get('nte_dns_get_created_by', {})
        serializer = DynamicUserSerializer(
            note.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_latest_version(self, note):
        context = self.context
        _context_fields = context.get('nte_dns_get_latest_version', {})
        serializer = DynamicNoteContentSerializer(
            note.latest_version,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_notes(self, note):
        context = self.context
        _context_fields = context.get('nte_dns_get_notes', {})
        serializer = DynamicNoteContentSerializer(
            note.notes,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_organization(self, note):
        context = self.context
        _context_fields = context.get('nte_dns_get_organization', {})
        serializer = DynamicOrganizationSerializer(
            note.organization,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_unified_document(self, note):
        context = self.context
        _context_fields = context.get('nte_dns_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            note.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data
