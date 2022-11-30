from datetime import datetime

import iso8601
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models.query_utils import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from hub.models import Hub
from reputation.models import Contribution
from researchhub_access_group.constants import EDITOR
from user.related_models.user_model import User
from user.serializers import EditorContributionSerializer
from utils.http import GET


def resolve_timeframe_for_contribution(start_date, end_date, query_key=None):

    dateFrame = {}

    if start_date:
        dateFrame[
            "contributions__created_date__gte"
            if query_key is None
            else query_key + "__gte"
        ] = start_date

    if end_date:
        dateFrame[
            "contributions__created_date__lte"
            if query_key is None
            else query_key + "__lte"
        ] = end_date

    return dateFrame


@api_view(http_method_names=[GET])
@permission_classes([AllowAny])
def get_hub_active_contributors(request):
    user_ids = request.GET.get("userIds", "").split(",")
    start_date = request.GET.get("startDate", None)
    end_date = request.GET.get("endDate", None)

    if end_date:
        end_date = end_date[:-6]
        end_date = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S")

    current_active_contributors = {}
    previous_active_contributors = {}
    for user_id in user_ids:
        user = User.objects.get(id=user_id)

        hub_content_type = ContentType.objects.get_for_model(Hub)
        target_permissions = user.permissions.filter(
            access_type=EDITOR, content_type=hub_content_type
        )
        target_hub_ids = []
        for permission in target_permissions:
            target_hub_ids.append(permission.object_id)

        total_active_contributors = (
            Contribution.objects.filter(
                contribution_type__in=[
                    Contribution.COMMENTER,
                    Contribution.SUBMITTER,
                    Contribution.SUPPORTER,
                    Contribution.UPVOTER,
                ],
                created_date__gte=start_date,
                created_date__lte=end_date,
                unified_document__hubs__in=target_hub_ids,
            )
            .distinct("user")
            .count()
        )
        current_active_contributors[user_id] = total_active_contributors

        days_between = iso8601.parse_date(end_date) - iso8601.parse_date(start_date)

        previous_contributors = (
            Contribution.objects.filter(
                contribution_type__in=[
                    Contribution.COMMENTER,
                    Contribution.SUBMITTER,
                    Contribution.SUPPORTER,
                    Contribution.UPVOTER,
                ],
                created_date__gte=iso8601.parse_date(start_date) - days_between,
                created_date__lte=iso8601.parse_date(end_date) - days_between,
                unified_document__hubs__in=target_hub_ids,
            )
            .distinct("user")
            .count()
        )

        previous_active_contributors[user_id] = previous_contributors

    return Response(
        {
            "previous_active_contributors": previous_active_contributors,
            "current_active_contributors": current_active_contributors,
        }
    )


@api_view(http_method_names=[GET])
@permission_classes([AllowAny])
def get_editors_by_contributions(request):
    editor_qs = User.objects.filter(
        permissions__isnull=False,
        permissions__access_type=EDITOR,
        permissions__content_type=ContentType.objects.get_for_model(Hub),
    ).distinct()

    start_date = request.GET.get("startDate", None)
    end_date = request.GET.get("endDate", None)
    timeframe_query = Q(
        **resolve_timeframe_for_contribution(start_date, end_date),
    )

    # NOTE: We need time_query at contributions level, NOT at editor_qs
    total_contrib_query = (
        Q(
            contributions__contribution_type__in=[
                Contribution.COMMENTER,
                Contribution.SUBMITTER,
                Contribution.SUPPORTER,
            ],
        )
        & timeframe_query
    )

    qs_key = "contributions__contribution_type"
    comment_query = Q(**dict([(qs_key, Contribution.COMMENTER)])) & timeframe_query

    submission_query = Q(**dict([(qs_key, Contribution.SUBMITTER)])) & timeframe_query

    support_query = Q(**dict([(qs_key, Contribution.SUPPORTER)])) & timeframe_query

    hub_id = request.GET.get("hub_id", None)
    if hub_id is not None:
        contribution_hub_query = Q(contributions__unified_document__hubs__in=[hub_id])
        editor_qs = editor_qs.filter(permissions__object_id=hub_id)
        total_contrib_query = total_contrib_query & contribution_hub_query
        comment_query = comment_query & contribution_hub_query
        submission_query = submission_query & contribution_hub_query
        support_query = support_query & contribution_hub_query

    editor_qs = editor_qs.prefetch_related(
        "contributions",
        "contributions__unified_document__hubs",
        "contributions__created_date__gte",
    )

    order_by = (
        "-total_contribution_count"
        if request.GET.get("order_by", "desc") == "desc"
        else "total_contribution_count"
    )

    editor_qs_ranked_by_contribution = editor_qs.annotate(
        total_contribution_count=Count("id", filter=total_contrib_query),
        comment_count=Count("id", filter=comment_query),
        submission_count=Count("id", filter=submission_query),
        support_count=Count("id", filter=support_query),
    ).order_by(order_by)

    paginator = Paginator(
        editor_qs_ranked_by_contribution,  # qs
        10,  # page size
    )
    curr_page_number = request.GET.get("page") or 1
    curr_pagation = paginator.page(curr_page_number)

    return Response(
        {
            "count": paginator.count,
            "has_more": curr_pagation.has_next(),
            "page": curr_page_number,
            "result": EditorContributionSerializer(
                curr_pagation.object_list,
                many=True,
                context={"target_hub_id": hub_id},
            ).data,
        },
        status=200,
    )
