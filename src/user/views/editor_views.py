from datetime import timedelta
from django.contrib.contenttypes.models import ContentType
from django.db.models.aggregates import Count, Sum
from django.db.models.functions.comparison import Coalesce
from django.db.models.query_utils import Q
from django.http import response
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from reputation.models import Contribution
from utils.http import GET

from hub.models import Hub
from hub.permissions import IsModerator
from researchhub_access_group.constants import EDITOR
from user.related_models.user_model import User


def resolve_timeframe_for_contribution(timeframe_str):
    keyword = 'reputation_records__created_date__gte'
    if timeframe_str == 'today':
        return {keyword: timezone.now().date()}
    elif timeframe_str == 'past_week':
        return {keyword: timezone.now().date() - timedelta(days=7)}
    elif timeframe_str == 'past_month':
        return {keyword: timezone.now().date() - timedelta(days=30)}


@api_view(http_method_names=[GET])
@permission_classes([IsModerator])
def get_editors_by_contributions(request):
    try:
        editor_qs = User.objects.filter(
          permissions__isnull=False,
          permissions__access_type=EDITOR,
          permissions__content_type=ContentType.objects.get_for_model(Hub)
        ).distinct()

        timeframe_str = request.GET.get('timeframe_str', None)
        resolved_timeframe = resolve_timeframe_for_contribution(timeframe_str)
        contribution_filter = Q(
            **resolved_timeframe,
            type__in=[
                Contribution.SUBMITTER,
                Contribution.COMMENTER,
                Contribution.SUPPORTER,
            ]
        )

        hub_id = request.GET.get('hub_id', None)
        if (hub_id is not None):
            editor_qs = editor_qs.filter(permissions__object_id=hub_id)
            contribution_filter = contribution_filter & \
                Q(unified_document__hubs__in=[hub_id])

        editor_qs_ranked_by_contribution = \
            editor_qs.annotate(
                contributions=Count(
                    'id', contribution_filter
                ),
                comment_count=Count(
                    'id', Q(type__in=[Contribution.COMMENTER])
                ),
                submission_count=Count(
                    'id', Q(type__in=[Contribution.COMMENTER])
                ),
                support_count=Count(
                    'id', Q(type__in=[Contribution.COMMENTER])
                ),
            ).order_by('-contribution_count')
        import pdb; pdb.set_trace()

    except Exception as error:
        return response(error, status=400)
