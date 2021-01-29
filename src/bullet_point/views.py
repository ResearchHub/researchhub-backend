from django.db import transaction
from django.views.decorators.cache import cache_page
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
    Vote,
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
    FlagSerializer,
    BulletPointVoteSerializer
)
from utils.http import DELETE, POST, PATCH, PUT
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES

from utils.siftscience import (
    events_api,
    decisions_api,
    update_user_risk_score
)

from reputation.models import Contribution
from reputation.tasks import create_contribution
from researchhub.lib import ActionableViewSet, get_paper_id_from_path
from .filters import BulletPointFilter


class BulletPointViewSet(viewsets.ModelViewSet, ActionableViewSet):
    queryset = BulletPoint.objects.all()
    serializer_class = BulletPointSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['is_head', 'ordinal', 'created_by__author_profile']
    filter_class = BulletPointFilter
    ordering = ['ordinal', '-created_date']
    ordering_fields = ['ordinal', 'created_date']
    pagination_class = PageNumberPagination

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateBulletPoint
        & UpdateOrDeleteBulletPoint
        & CreateOrUpdateIfAllowed
    ]
    throttle_classes = THROTTLE_CLASSES

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

        context = self.get_serializer_context()
        response = super().create(request, *args, **kwargs)
        bullet_id = response.data['id']

        bullet_point = BulletPoint.objects.get(pk=response.data['id'])
        update_or_create_vote(request, request.user, bullet_point, Vote.UPVOTE)
        response.data = BulletPointSerializer(
            bullet_point,
            context=context
        ).data

        tracked_bullet_point = events_api.track_content_bullet_point(
            bullet_point.created_by,
            bullet_point,
            request,
        )
        update_user_risk_score(bullet_point.created_by, tracked_bullet_point)

        create_contribution.apply_async(
            (
                Contribution.CURATOR,
                {'app_label': 'bullet_point', 'model': 'bulletpoint'},
                request.user.id,
                paper,
                bullet_id
            ),
            priority=2,
            countdown=10
        )
        return response

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
        bullet_point.save(update_fields=['is_removed'])

        content_id = f'{type(bullet_point).__name__}_{bullet_point.id}'
        user = request.user
        content_creator = bullet_point.created_by
        events_api.track_flag_content(
            content_creator,
            content_id,
            user.id
        )
        decisions_api.apply_bad_content_decision(
            content_creator,
            content_id,
            'MANUAL_REVIEW',
            user
        )
        decisions_api.apply_bad_user_decision(
            content_creator,
            'MANUAL_REVIEW',
            user
        )

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
                bullet_type=bullet_point.bullet_type,
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

            tracked_bullet_point = events_api.track_content_bullet_point(
                head_bullet_point.created_by,
                head_bullet_point,
                request,
                update=True
            )
            update_user_risk_score(head_bullet_point.created_by, tracked_bullet_point)

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

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            CreateOrUpdateIfAllowed
        ]
    )
    def upvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.UPVOTE)
        return response

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.DOWNVOTE)
        return response


def create_vote(user, bulletpoint, vote_type):
    vote = Vote(
        created_by=user,
        bulletpoint=bulletpoint,
        vote_type=vote_type
    )
    vote.save()
    return vote


def find_vote(user, bulletpoint, vote_type):
    vote = Vote.objects.filter(
        bulletpoint=bulletpoint,
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def retrieve_vote(user, bulletpoint):
    try:
        return Vote.objects.get(
            bulletpoint=bulletpoint,
            created_by=user.id
        )
    except Vote.DoesNotExist:
        return None


def get_vote_response(vote, status_code):
    serializer = BulletPointVoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def update_or_create_vote(request, user, bulletpoint, vote_type):
    vote = retrieve_vote(user, bulletpoint)

    if vote:
        vote.vote_type = vote_type
        vote.save(update_fields=['updated_date', 'vote_type'])
        events_api.track_content_vote(user, vote, request)
        return get_vote_response(vote, 200)

    vote = create_vote(user, bulletpoint, vote_type)
    events_api.track_content_vote(user, vote, request)
    create_contribution.apply_async(
        (
            Contribution.UPVOTER,
            {'app_label': 'bullet_point', 'model': 'vote'},
            user.id,
            bulletpoint.paper.id,
            vote.id
        ),
        priority=3,
        countdown=10
    )
    return get_vote_response(vote, 201)
