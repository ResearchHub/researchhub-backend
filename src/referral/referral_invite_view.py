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
from utils.permissions import PostOnly

from .related_models.referral_invite import BOUNTY, JOIN_RH


class ReferralInviteViewSet(viewsets.ModelViewSet):
    serializer_class = ReferralInviteSerializer
    permission_classes = [IsAuthenticated, PostOnly]
    queryset = ReferralInvite.objects.all()

    def create(self, request):
        one_day_in_minutes = 1440
        invite_data = {}
        invite_data = {**request.data, "inviter": request.user.id}

        is_recipient_already_user = User.objects.filter(
            email=invite_data["recipient_email"]
        ).exists()
        if is_recipient_already_user:
            return Response(
                {"message": "Person is already a ResearchHub user", "error": True},
                status=status.HTTP_409_CONFLICT,
            )

        is_already_sent = ReferralInvite.objects.filter(
            inviter=request.user,
            invite_type=invite_data["invite_type"],
            recipient_email=invite_data["recipient_email"],
            expiration_date__lte=datetime.now(),
            expiration_date__gte=datetime.now() - timedelta(minutes=one_day_in_minutes),
        )

        if invite_data["invite_type"] not in [JOIN_RH, BOUNTY]:
            return Response(
                {"message": "Invalid invite type", "error": True},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if is_already_sent:
            return Response(
                {"message": "Invite already sent", "error": True},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = ReferralInviteSerializer(data=invite_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        if not TESTING:
            serializer.instance.send_invitation()

        return Response(serializer.data)
