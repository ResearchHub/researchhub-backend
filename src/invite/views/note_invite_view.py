from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from invite.models import NoteInvitation
from invite.serializers import NoteInvitationSerializer
from researchhub_access_group.models import Permission


class NoteInvitationViewSet(ModelViewSet):
    queryset = NoteInvitation.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = NoteInvitationSerializer

    def get_queryset(self):
        return self.queryset.filter(recipient=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def accept_invite(self, request, pk=None):
        user = request.user
        invite = self.queryset.get(key=pk)

        if invite.is_expired() or invite.accepted:
            return Response({"data": "Invitation has expired"}, status=403)

        if invite.recipient and user != invite.recipient:
            return Response({"data": "Invalid invitation"}, status=400)

        note = invite.note
        invite_type = invite.invite_type
        unified_document = note.unified_document
        permissions = note.unified_document.permissions
        content_type = ContentType.objects.get_for_model(unified_document)

        if not permissions.filter(user=user).exists():
            Permission.objects.create(
                access_type=invite_type,
                content_type=content_type,
                object_id=unified_document.id,
                user=user,
            )

        invite.accept()

        return Response({"data": "User has accepted invitation"}, status=200)
