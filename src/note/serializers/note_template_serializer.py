from rest_framework.serializers import ModelSerializer, SerializerMethodField

from note.models import NoteTemplate
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import (
    DynamicOrganizationSerializer,
    DynamicUserSerializer
)


class NoteTemplateSerializer(ModelSerializer):
    src = SerializerMethodField()

    class Meta:
        model = NoteTemplate
        fields = '__all__'

    def get_src(self, note_content):
        src = note_content.src
        if src:
            byte_string = note_content.src.read()
            data = byte_string.decode('utf-8')
            return data
        return None


class DynamicNoteTemplateSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    organization = SerializerMethodField()

    class Meta:
        model = NoteTemplate
        fields = '__all__'

    def get_created_by(self, note_template):
        context = self.context
        _context_fields = context.get('nte_dnts_get_created_by', {})
        serializer = DynamicUserSerializer(
            note_template.created_by,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_organization(self, note_template):
        context = self.context
        _context_fields = context.get('nte_dnts_get_organization', {})
        serializer = DynamicOrganizationSerializer(
            note_template.organization,
            context=context,
            **_context_fields
        )
        return serializer.data
