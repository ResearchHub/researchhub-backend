from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated,
)
from peer_review.models import PeerReviewInvite
from peer_review.serializers import (
    PeerReviewInviteSerializer,
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


    def list(self, request, pk=None):
        print('implement')
        # queryset = self.get_queryset()

        # if request.user.moderator:
        #     queryset = self.queryset
        # else:
        #     queryset = self.queryset.filter(requested_by_user=request.user)

        # page = self.paginate_queryset(queryset)
        # serializer = PeerReviewRequestSerializer(page, many=True)
        # return self.get_paginated_response(serializer.data)

    @action(
        detail=False,
        methods=[POST],
        permission_classes=[IsAllowedToInvite]
    )
    def invite(self, request, *args, **kwargs):
        request.data['inviter'] = request.user.id
        serializer = PeerReviewInviteSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        invite = serializer.data
        if invite['recipient'] is not None:
            invite['recipient_email'] = None

        return Response(invite)

    @action(
        detail=True,
        methods=[POST],
        permission_classes=[IsAllowedToAcceptInvite]
    )
    def accept(self, request, pk=None):
        print('here')
        # if 
        # invite.accept()
