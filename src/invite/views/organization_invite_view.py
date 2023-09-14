from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from invite.models import OrganizationInvitation
from invite.serializers import OrganizationInvitationSerializer
from researchhub_access_group.models import Permission
from user.models import Gatekeeper, Organization


class OrganizationInvitationViewSet(ModelViewSet):
    queryset = OrganizationInvitation.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationInvitationSerializer

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def accept_invite(self, request, pk=None):
        user = request.user
        invite = self.queryset.get(key=pk)

        if invite.is_expired() or invite.accepted:
            return Response({"data": "Invitation has expired"}, status=403)

        if invite.recipient and user != invite.recipient:
            return Response({"data": "Invalid invitation"}, status=400)

        content_type = ContentType.objects.get_for_model(Organization)
        invite_type = invite.invite_type
        organization = invite.organization
        permissions = organization.permissions

        if not permissions.filter(user=user).exists():
            Permission.objects.create(
                access_type=invite_type,
                content_type=content_type,
                object_id=organization.id,
                user=user,
            )
        invite.accept()

        # Temporary code to invite people to reference manager via gatekeeper
        inviter = invite.inviter
        if Gatekeeper.objects.filter(user=inviter, type="REFERENCE_MANAGER").exists():
            Gatekeeper.objects.create(user=user, type="REFERENCE_MANAGER")

        return Response({"data": "User has accepted invitation"}, status=200)

    @action(detail=False, methods=["post"])
    def check_user_status(self, request):
        data = request.data
        user_id = data.get("user")
        organization_id = data.get("organization")

        organization = Organization.objects.get(id=organization_id)
        invites = self.queryset.filter(
            organization=organization,
            recipient=user_id,
            accepted=True,
        ).distinct("accepted")
        serializer = self.serializer_class(invites, many=True)
        return Response(serializer.data, status=200)
