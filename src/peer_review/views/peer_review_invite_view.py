from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated,
)
from user.models import User
from peer_review.models import (
    PeerReviewInvite,
    PeerReview,
)
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

        reviewer = User.objects.get(email=invite.recipient_email)
        review = PeerReview.objects.create(
            assigned_user=reviewer,
            unified_document=invite.peer_review_request.unified_document,
        )

        invite.peer_review_request.peer_review = review
        invite.peer_review_request.save()

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
