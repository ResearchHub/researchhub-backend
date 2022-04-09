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

        return Response(serializer.data)

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

        serializer = self.serializer_class(invite)
        data = serializer.data

        return Response(data)

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
