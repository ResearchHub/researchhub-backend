from datetime import timedelta
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max,DateTimeField, OuterRef, Subquery
from django.db.models.functions import Cast
from django.db.models.query_utils import Q
from django.utils import timezone
from reputation.models import Contribution
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from user.serializers import EditorContributionSerializer
from utils.http import GET

from rest_framework.permissions import AllowAny

from hub.models import Hub
from hub.permissions import IsModerator
from researchhub_access_group.constants import EDITOR
from user.related_models.user_model import User


def resolve_timeframe_for_contribution(timeframe_str):
    keyword = 'contributions__created_date__gte'
    if timeframe_str == 'today':
        return {keyword: timezone.now().date()}
    elif timeframe_str == 'past_week':
        return {keyword: timezone.now().date() - timedelta(days=7)}
    elif timeframe_str == 'past_month':
        return {keyword: timezone.now().date() - timedelta(days=30)}
    else:
        return {}


@api_view(http_method_names=[GET])
@permission_classes([AllowAny])
def get_editors_by_contributions(request):
    try:
        editor_qs = User.objects.filter(
            permissions__isnull=False,
            permissions__access_type=EDITOR,
            permissions__content_type=ContentType.objects.get_for_model(Hub)
        ).distinct()

        timeframe_query = Q(
            **resolve_timeframe_for_contribution(
                request.GET.get('timeframe_str', None)
            ),
        )

        # NOTE: We need time_query at contributions level, NOT at editor_qs
        total_contrib_query = Q(
            contributions__contribution_type__in=[
              Contribution.COMMENTER,
              Contribution.SUBMITTER,
              Contribution.SUPPORTER,
            ],
        ) & timeframe_query

        comment_query = Q(
            contributions__contribution_type=Contribution.COMMENTER
        ) & timeframe_query

        submission_query = Q(
            contributions__contribution_type=Contribution.SUBMITTER
        ) & timeframe_query

        support_query = Q(
            contributions__contribution_type=Contribution.SUPPORTER
        ) & timeframe_query

        hub_id = request.GET.get('hub_id', None)
        if (hub_id is not None):
            contribution_hub_query = Q(
                contributions__unified_document__hubs__in=[hub_id]
            )

            editor_qs = editor_qs.filter(
              permissions__object_id=hub_id
            )
            total_contrib_query = \
                total_contrib_query & contribution_hub_query
            comment_query = \
                comment_query & contribution_hub_query
            submission_query = \
                submission_query & contribution_hub_query
            support_query = \
                support_query & contribution_hub_query

        editor_qs = editor_qs.prefetch_related(
          'contributions',
          'contributions__unified_document__hubs',
          'contributions__created_date__gte',
        )

        order_by = '-total_contribution_count' \
            if request.GET.get('order_by', 'desc') == 'desc' \
            else 'total_contribution_count'

        editor_qs_ranked_by_contribution = \
            editor_qs.annotate(
                total_contribution_count=Count(
                    'id', filter=total_contrib_query
                ),
                comment_count=Count(
                    'id', filter=comment_query
                ),
                submission_count=Count(
                    'id', filter=submission_query
                ),
                support_count=Count(
                    'id', filter=support_query
                ),
            ).order_by(order_by)

        return Response(
            EditorContributionSerializer(
                editor_qs_ranked_by_contribution,
                many=True,
                context={'target_hub_id': hub_id},
            ).data,
            status=200
        )
    except Exception as error:
        return Response(error, status=400)
