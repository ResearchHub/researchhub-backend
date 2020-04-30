from django.db import transaction
from django.db.models import Q, F
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
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

from .filters import BulletPointFilter


class BulletPointViewSet(viewsets.ModelViewSet, ActionableViewSet):
    queryset = BulletPoint.objects.all()
    serializer_class = BulletPointSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['is_head', 'ordinal']
    filter_class = BulletPointFilter
    ordering = ['ordinal', '-created_date']
    ordering_fields = ['ordinal', 'created_date']
    pagination_class = PageNumberPagination

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateBulletPoint
        & UpdateOrDeleteBulletPoint
    ]

    def get_queryset(self):
        filters = {}

        paper_id = get_paper_id_from_path(self.request)
        if paper_id is not None:
            filters['paper'] = paper_id
        bullet_type = self.request.query_params.get('bullet__type', None)
        only_heads = not self.request.query_params.get('all', False)

        if only_heads:
            filters['is_head'] = True
        if bullet_type is not None:
            filters['bullet_type'] = bullet_type

        if paper_id is None:
            bullet_points = BulletPoint.objects.all()
        else:
            bullet_points = BulletPoint.objects.filter(**filters)
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
        permission_classes=[IsAuthenticated, CreateBulletPoint]
    )
    def edit(self, request, pk=None):
        bullet_point = self.get_object()
        user = request.user
        paper_id = request.data.get('paper', None)
        if paper_id is None:
            paper_id = get_paper_id_from_path(request)
            if paper_id is None:
                return Response(
                    'Missing required field `paper`',
                    status=status.HTTP_400_BAD_REQUEST
                )
        text = request.data.get('text')
        plain_text = request.data.get('plain_text')

        tail = bullet_point.tail
        if tail is None:
            tail = bullet_point

        with transaction.atomic():
            head_bullet_point = BulletPoint.objects.create(
                paper_id=paper_id,
                tail=tail,
                previous=bullet_point,
                created_by=user,
                text=text,
                plain_text=plain_text,
                ordinal=bullet_point.ordinal,
                ordinal_is_locked=bullet_point.ordinal_is_locked,
                is_head=True,
                is_tail=False
            )
            bullet_point.remove_from_head()
            bullet_point.save()

        serialized = self.get_serializer(instance=head_bullet_point)
        return Response(serialized.data, status=status.HTTP_201_CREATED)

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

    @action(detail=True, methods=[PATCH], permission_classes=[IsAuthenticated])
    def reorder(self, request, pk=None):
        bullet_point = self.get_object()
        ordinal = request.data.get('ordinal')
        bullet_point.set_ordinal(ordinal)
        serialized = self.get_serializer(instance=bullet_point)
        return Response(serialized.data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=[PATCH],
        permission_classes=[IsAuthenticated]
    )
    def reorder_all(self, request):
        order = request.data.get('order', None)
        bullet_type = request.data.get('bullet_type')
        if (order is None) or (type(order) is not list):
            return Response(
                'Request body `order` must be a list of integers',
                status=status.HTTP_400_BAD_REQUEST
            )
        # TODO: This is a quick fix but we should get the paper from params
        bp = BulletPoint.objects.get(pk=order[0])
        paper = bp.paper

        BulletPoint.objects.filter(
            id__in=order,
            paper=paper,
            ordinal__isnull=False,
            is_head=True,
            bullet_type=bullet_type
        ).update(ordinal=None)

        try:
            with transaction.atomic():
                ordinal = 0
                for pk in order:
                    ordinal += 1
                    BulletPoint.objects.filter(pk=pk).update(ordinal=ordinal)
        except Exception as e:
            return Response(str(e), status=status.HTTP_400_BAD_REQUEST)

        return Response('Success', status=status.HTTP_200_OK)

    def upvote(self, *args, **kwargs):
        pass

    def downvote(self, *args, **kwargs):
        pass

    def user_vote(self, *args, **kwargs):
        pass
