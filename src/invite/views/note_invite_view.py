from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from invite.models import NoteInvitation
from invite.serializers import NoteInvitationSerializer
from invite.services import (
    NoteInvitationExpiredError,
    NoteInvitationRecipientMismatchError,
    NoteInvitationService,
)


class NoteInvitationViewSet(ModelViewSet):
    queryset = NoteInvitation.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = NoteInvitationSerializer

    def get_queryset(self):
        return self.queryset.filter(recipient=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def accept_invite(self, request, pk=None):
        service = NoteInvitationService()

        try:
            service.accept_invite(pk, request.user)
        except NoteInvitationExpiredError:
            return Response({"data": "Invitation has expired"}, status=403)
        except NoteInvitationRecipientMismatchError:
            return Response({"data": "Invalid invitation"}, status=400)

        return Response({"data": "User has accepted invitation"}, status=200)
