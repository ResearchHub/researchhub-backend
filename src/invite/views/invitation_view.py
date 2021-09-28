from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import (
    IsAuthenticated,
)

from invite.models import OrganizationInvitation
from invite.serializers import OrganizationInvitationSerializer


class OrganizationInvitationViewSet(ModelViewSet):
    queryset = OrganizationInvitation.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationInvitationSerializer

    @action(detail=True, methods=['post'])
    def accept_invite(self, request, pk=None):
        user = request.user
        invite = self.queryset.get(key=pk)

        if invite.is_expired():
            return Response('Invitation has expired', status=403)

        if user != invite.recipient:
            return Response('Invalid invitation', status=400)

        invite_type = invite.invite_type
        access_group = invite.organization.access_group
        if invite_type == OrganizationInvitation.ADMIN:
            access_group.admins.add(user)
        elif invite_type == OrganizationInvitation.EDITOR:
            access_group.editors.add(user)
        else:
            access_group.viewers.add(user)

        invite.accept()

        return Response('User has accepted invitation', status=200)
