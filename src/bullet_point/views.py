from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.response import Response

from bullet_point.models import (
    BulletPoint,
    create_endorsement,
    create_flag,
    retrieve_endorsement,
    retrieve_flag
)
from bullet_point.permissions import (
    Censor,
    CreateBulletPoint,
    Endorse,
    Flag,
    UpdateOrDeleteBulletPoint,
    check_user_is_moderator
)
from bullet_point.serializers import (
    BulletPointSerializer,
    EndorsementSerializer,
    FlagSerializer
)
from researchhub.lib import ActionableViewSet, get_paper_id_from_path
from utils.http import DELETE, POST, PATCH, PUT


class BulletPointViewSet(viewsets.ModelViewSet, ActionableViewSet):
    queryset = BulletPoint.objects.all()
    serializer_class = BulletPointSerializer

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateBulletPoint
        & UpdateOrDeleteBulletPoint
    ]

    def get_queryset(self):
        paper_id = get_paper_id_from_path(self.request)
        if paper_id is None:
            bullet_points = BulletPoint.objects.all()
        else:
            bullet_points = BulletPoint.objects.filter(paper=paper_id)
        return bullet_points

    def create(self, request, *args, **kwargs):
        # Do not allow user to manually set created_by
        try:
            del request.data['created_by']
        except KeyError:
            pass

        paper = request.data.get('paper', None)
        if paper is None:
            paper = get_paper_id_from_path(request)
            if paper is None:
                return Response('Missing required field `paper`', status=400)
            request.data['paper'] = paper
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if (
            not self._permit_lock_ordinal(request)
            or not self._permit_remove(request)
            or not self._permit_set_created_by(request)
        ):
            return Response('You do not have permission', status=400)
        return super().update(request, *args, **kwargs)

    def _permit_lock_ordinal(self, request):
        if request.data.get('ordinal_is_locked', None) is not None:
            bullet_point = self.get_object()
            return check_user_is_moderator(request.user, bullet_point)
        return True

    def _permit_remove(self, request):
        if request.data.get('is_removed', None) is not None:
            bullet_point = self.get_object()
            return check_user_is_moderator(request.user, bullet_point)
        return True

    def _permit_set_created_by(self, request):
        return request.data.get('created_by', None) is None  # Never permit

    @action(
        detail=True,
        methods=[DELETE, PATCH, PUT],
        permission_classes=[IsAuthenticated, Censor]
    )
    def censor(self, request, pk=None):
        bullet_point = self.get_object()
        bullet_point.is_removed = True
        bullet_point.save()
        return Response(
            self.get_serializer(instance=bullet_point).data,
            status=200
        )

    @action(
        detail=True,
        methods=[POST],
        permission_classes=[Endorse]
    )
    def endorse(self, request, pk=None):
        bullet_point = self.get_object()
        user = request.user
        try:
            endorsement = create_endorsement(user, bullet_point)
            serialized = EndorsementSerializer(endorsement)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create endorsement: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    @endorse.mapping.delete
    def delete_endorse(self, request, pk=None):
        bullet_point = self.get_object()
        user = request.user
        try:
            endorsement = retrieve_endorsement(user, bullet_point)
            endorsement_id = endorsement.id
            endorsement.delete()
            return Response(endorsement_id, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete endorsement: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        detail=True,
        methods=[POST],
        permission_classes=[Flag]
    )
    def flag(self, request, pk=None):
        bullet_point = self.get_object()
        user = request.user
        reason = request.data.get('reason')
        try:
            flag = create_flag(user, bullet_point, reason)
            serialized = FlagSerializer(flag)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create flag: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    @flag.mapping.delete
    def delete_flag(self, request, pk=None):
        bullet_point = self.get_object()
        user = request.user
        try:
            flag = retrieve_flag(user, bullet_point)
            flag_id = flag.id
            flag.delete()
            return Response(flag_id, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete flag: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    def upvote(self, *args, **kwargs):
        pass

    def downvote(self, *args, **kwargs):
        pass

    def user_vote(self, *args, **kwargs):
        pass
