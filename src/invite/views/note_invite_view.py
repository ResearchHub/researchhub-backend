from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny
)

from invite.models import NoteInvitation
from invite.serializers import NoteInvitationSerializer
from researchhub_access_group.models import Permission


class NoteInvitationViewSet(ModelViewSet):
    queryset = NoteInvitation.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = NoteInvitationSerializer

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[AllowAny]
    )
    def accept_invite(self, request, pk=None):
        user = request.user
        invite = self.queryset.get(key=pk)

        if invite.is_expired() or invite.accepted:
            return Response({'data': 'Invitation has expired'}, status=403)

        if invite.recipient and user != invite.recipient:
            return Response({'data': 'Invalid invitation'}, status=400)

        note = invite.note
        invite_type = invite.invite_type
        permission = Permission.objects.create(
            access_type=invite_type,
            user=user
        )

        note.unified_document.permissions.add(permission)
        invite.accept()

        return Response({'data': 'User has accepted invitation'}, status=200)
