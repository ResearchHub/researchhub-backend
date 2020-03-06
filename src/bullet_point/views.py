from rest_framework import viewsets
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly
)
from rest_framework.response import Response

from bullet_point.models import BulletPoint
from bullet_point.permissions import (
    CreateBulletPoint,
    UpdateOrDeleteBulletPoint,
    check_user_is_moderator
)
from bullet_point.serializers import BulletPointSerializer
from researchhub.lib import get_paper_id_from_path


class BulletPointViewSet(viewsets.ModelViewSet):
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
