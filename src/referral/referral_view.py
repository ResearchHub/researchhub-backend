from datetime import datetime, timedelta

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from referral.related_models.referral_invite import ReferralInvite
from referral.serializers.referral_invite_serializer import ReferralInviteSerializer
from researchhub.settings import TESTING
from user.related_models.user_model import User
from utils.http import POST

from .related_models.referral_invite import BOUNTY, JOIN_RH


class ReferralViewSet(viewsets.ModelViewSet):
    @action(detail=False, methods=[POST], permission_classes=[IsAuthenticated])
    def invite(self, request):
        inviter = request.user
        data = request.data
        recipient_email = data.get("email")
        invite_type = data.get("type")

        one_day_in_minutes = 1440

        is_recipient_already_user = User.objects.filter(email=recipient_email).exists()
        if is_recipient_already_user:
            return Response(
                {"message": "This person is already a user"},
                status=status.HTTP_409_CONFLICT,
            )

        is_already_sent = ReferralInvite.objects.filter(
            inviter=inviter,
            invite_type=invite_type,
            recipient_email=recipient_email,
            expiration_date__lte=datetime.now(),
            expiration_date__gte=datetime.now() - timedelta(minutes=one_day_in_minutes),
        )

        if invite_type not in [JOIN_RH, BOUNTY]:
            return Response(
                {"message": "Invalid invite type"}, status=status.HTTP_400_BAD_REQUEST
            )
        if is_already_sent:
            return Response(
                {"message": "Invalid already sent"}, status=status.HTTP_409_CONFLICT
            )

        invite = ReferralInvite.create(
            inviter=inviter,
            invite_type=invite_type,
            recipient_email=recipient_email,
            expiration_time=10080,
        )

        if not TESTING:
            invite.send_invitation()

        return Response(
            ReferralInviteSerializer(invite).data, status=status.HTTP_201_CREATED
        )
