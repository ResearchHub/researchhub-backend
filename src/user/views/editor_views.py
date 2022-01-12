from datetime import timedelta
from django.contrib.contenttypes.models import ContentType
from django.db.models.aggregates import Count
from django.db.models.query_utils import Q
from django.utils import timezone
from rest_framework.response import Response
from reputation.models import Contribution
from rest_framework.decorators import api_view, permission_classes
from utils.http import GET
from rest_framework.permissions import AllowAny

from hub.models import Hub
from hub.permissions import IsModerator
from researchhub_access_group.constants import EDITOR
from user.related_models.user_model import User


def resolve_timeframe_for_contribution(timeframe_str):
    keyword = 'created_date__gte'
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

        timeframe_str = request.GET.get('timeframe_str', None)
        timeframe_query = Q(
          **resolve_timeframe_for_contribution(timeframe_str),
        )

        total_contrib_count_query = Q(
            contributions__contribution_type__in=[
              Contribution.COMMENTER,
              Contribution.SUBMITTER,
              Contribution.SUPPORTER,
            ],
        ) & timeframe_query

        comment_count_query = Q(
            contributions__contribution_type=Contribution.COMMENTER
        ) & timeframe_query

        submission_count_query = Q(
            contributions__contribution_type=Contribution.SUBMITTER
        ) & timeframe_query

        support_count_query = Q(
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
            total_contrib_count_query = \
                total_contrib_count_query & contribution_hub_query
            comment_count_query = \
                comment_count_query & contribution_hub_query
            submission_count_query = \
                submission_count_query & contribution_hub_query
            support_count_query = \
                support_count_query & contribution_hub_query

        editor_qs = editor_qs.prefetch_related(
          'contributions',
          'contributions__unified_document__hubs'
          'contributions__created_date__gte'
        )

        editor_qs_ranked_by_contribution = \
            editor_qs.annotate(
                total_contribution_count=Count(
                    'id', filter=total_contrib_count_query
                ),
                comment_count=Count(
                    'id', filter=comment_count_query
                ),
                submission_count=Count(
                    'id', filter=submission_count_query
                ),
                support_count=Count(
                    'id', filter=support_count_query
                ),
            ).order_by('-total_contribution_count')
        return Response({}, status=200)
    except Exception as error:
        return Response(error, status=400)
