from rest_framework.serializers import ModelSerializer, SerializerMethodField

from invite.models import NoteInvitation
from note.serializers import DynamicNoteSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicUserSerializer


class NoteInvitationSerializer(ModelSerializer):
    class Meta:
        model = NoteInvitation
        fields = '__all__'


class DynamicNoteInvitationSerializer(DynamicModelFieldSerializer):
    inviter = SerializerMethodField()
    note = SerializerMethodField()
    recipient = SerializerMethodField()

    class Meta:
        model = NoteInvitation
        fields = '__all__'

    def get_inviter(self, invitation):
        context = self.context
        _context_fields = context.get('inv_dnis_get_inviter', {})
        serializer = DynamicUserSerializer(
            invitation.inviter,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_note(self, invitation):
        context = self.context
        _context_fields = context.get('inv_dnis_get_note', {})
        serializer = DynamicNoteSerializer(
            invitation.note,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_recipient(self, invitation):
        context = self.context
        _context_fields = context.get('inv_dnis_get_recipient', {})
        serializer = DynamicUserSerializer(
            invitation.recipient,
            context=context,
            **_context_fields
        )
        return serializer.data
