from datetime import timedelta
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.db.models.query_utils import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from hub.models import Hub
from reputation.models import Contribution
from researchhub_access_group.constants import EDITOR
from user.related_models.user_model import User
from user.serializers import EditorContributionSerializer
from django.core.paginator import Paginator
from utils.http import GET

def resolve_timeframe_for_contribution(startDate, endDate):

    dateFrame = {}

    if startDate:
        dateFrame['contributions__created_date__gte'] = startDate

    if endDate:
        dateFrame['contributions__created_date__lte'] = endDate

    return dateFrame

@api_view(http_method_names=[GET])
@permission_classes([AllowAny])
def get_editors_by_contributions(request):
    editor_qs = User.objects.filter(
        permissions__isnull=False,
        permissions__access_type=EDITOR,
        permissions__content_type=ContentType.objects.get_for_model(Hub)
    ).distinct()

    timeframe_query = Q(
        **resolve_timeframe_for_contribution(
            request.GET.get('startDate', None),
            request.GET.get('endDate', None)
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

    paginator = Paginator(
        editor_qs_ranked_by_contribution,  # qs
        10,  # page size
    )
    curr_page_number = request.GET.get('page') or 1
    curr_pagation = paginator.page(curr_page_number)

    return Response(
        {
            'count': paginator.count,
            'has_more': curr_pagation.has_next(),
            'page': curr_page_number,
            'result': EditorContributionSerializer(
                curr_pagation.object_list,
                many=True,
                context={'target_hub_id': hub_id},
            ).data,
        },
        status=200
    )
