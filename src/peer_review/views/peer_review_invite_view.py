from regex import P
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated,
)
from peer_review.related_models.peer_review_request_model import PeerReviewRequest
from user.models import User
from peer_review.models import (
    PeerReviewInvite,
    PeerReview,
)
from peer_review.serializers import (
    PeerReviewInviteSerializer,
    DynamicPeerReviewInviteSerializer
)
from peer_review.permissions import (
    IsAllowedToInvite,
    IsAllowedToAcceptInvite
)
from rest_framework.response import Response
from rest_framework.decorators import action
from utils.http import DELETE, POST, PATCH, PUT, GET


class PeerReviewInviteViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = PeerReviewInviteSerializer
    queryset = PeerReviewInvite.objects.all()

    @action(
        detail=False,
        methods=[POST],
        permission_classes=[IsAllowedToInvite]
    )
    def invite(self, request, *args, **kwargs):
        invite_data = request.data
        invite_data['inviter'] = request.user.id

        is_invited_by_email = request.data.get('recipient_email', False)
        is_invited_by_user_id = request.data.get('recipient', False)

        if is_invited_by_email:
            recipient_user = User.objects.filter(email=request.data['recipient_email']).first()
            if recipient_user:
                invite_data['recipient'] = recipient_user.id
        elif is_invited_by_user_id:
            recipient_user = User.objects.get(id=request.data['recipient'])
            invite_data['recipient_email'] = recipient_user.email

        serializer = PeerReviewInviteSerializer(
            data=invite_data,
            context={'request': request}
        )

        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data)

    def _get_serializer_context(self):
        context = {
            'pr_dpris_get_recipient': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'author_profile',
                ]
            }
        }
        return context

    @action(
        detail=True,
        methods=[POST],
        permission_classes=[IsAllowedToAcceptInvite]
    )
    def accept(self, request, pk=None):
        invite = self.get_object()
        invite.status = PeerReviewInvite.ACCEPTED
        invite.save()
        invite.accept()

        # serializer = self.serializer_class(invite)
        # data = serializer.data

        context = self._get_serializer_context()
        serializer = DynamicPeerReviewInviteSerializer(
            invite,
            _include_fields=[
                'id',
                'unified_document',
                'requested_by_user',
                'created_date',
            ],
            context=context,
            many=True
        )

        return Response(serializer.data)

    @action(
        detail=True,
        methods=[POST],
        permission_classes=[IsAllowedToAcceptInvite]
    )
    def decline(self, request, pk=None):
        invite = self.get_object()
        invite.status = PeerReviewInvite.DECLINED
        invite.save()

        serializer = self.serializer_class(invite)
        data = serializer.data

        return Response(data)
