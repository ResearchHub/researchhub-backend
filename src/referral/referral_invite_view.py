from datetime import datetime, timedelta

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from referral.related_models.referral_invite import ReferralInvite
from referral.serializers.referral_invite_serializer import ReferralInviteSerializer
from user.related_models.user_model import User
from utils.http import POST

from .related_models.referral_invite import BOUNTY, JOIN_RH


class ReferralInviteViewSet(viewsets.ModelViewSet):
    serializer_class = ReferralInviteSerializer
    permission_classes = [
        IsAuthenticated,
    ]

    def create(self, request):
        inviter = request.user
        data = request.data

        one_day_in_minutes = 1440
        invite_data = {}
        invite_data["inviter"] = request.user.id
        invite_data["recipient_email"] = data.get("email")
        invite_data["invite_type"] = data.get("type")
        invite_data["referral_first_name"] = data.get("first_name")
        invite_data["referral_last_name"] = data.get("last_name")
        invite_data["unified_document"] = data.get("unified_document_id")

        is_recipient_already_user = User.objects.filter(
            email=invite_data["recipient_email"]
        ).exists()
        # if is_recipient_already_user:
        #     return Response(
        #         {"message": "Person is already a ResearchHub user", "error": True},
        #         status=status.HTTP_409_CONFLICT,
        #     )

        is_already_sent = ReferralInvite.objects.filter(
            inviter=inviter,
            invite_type=invite_data["invite_type"],
            recipient_email=invite_data["recipient_email"],
            expiration_date__lte=datetime.now(),
            expiration_date__gte=datetime.now() - timedelta(minutes=one_day_in_minutes),
        )

        # if invite_type not in [JOIN_RH, BOUNTY]:
        #     return Response(
        #         {"message": "Invalid invite type", "error": True}, status=status.HTTP_400_BAD_REQUEST
        #     )
        # if is_already_sent:
        #     return Response(
        #         {"message": "Invalid already sent", "error": True}, status=status.HTTP_409_CONFLICT
        #     )

        serializer = ReferralInviteSerializer(
            data=invite_data, context={"request": request}
        )

        serializer.is_valid(raise_exception=True)
        print(serializer.validated_data)
        self.perform_create(serializer)

        return Response(serializer.data)
