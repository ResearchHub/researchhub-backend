from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from google_analytics.utils import get_event_hit_response
from paper.models import Paper
from utils.http import POST
from utils.parsers import iso_string_to_datetime


@api_view(http_method_names=[POST])
@permission_classes(())  # Override default permission classes
def forward_event(request):
    try:
        utc = request.data['utc']
        utc_datetime = iso_string_to_datetime(utc)
    except KeyError as e:
        return Response(f'Missing post body data: {e}', status=400)
    except Exception as e:
        return Response(str(e), status=400)

    if request.query_params.get('manual') == 'true':
        try:
            event = [
                request.data['category'],
                request.data['action'],
                request.data['label'],
            ]
            value = request.data['value']
        except KeyError as e:
            return Response(f'Missing post body data: {e}', status=400)

        response = get_event_hit_response(*event, utc_datetime, value=value)
        if response.ok:
            return Response('Success', status=200)
        return Response('Failed', status=500)

    interaction = request.data['interaction']
    item = request.data['item']

    if request.query_params.get('ignore_user') == 'true':
        user = None
    else:
        user = request.user
        if user.is_anonymous:
            user = 'None'

    if request.query_params.get('ignore_paper') == 'true':
        paper = None
    else:
        paper = request.data['paper']
        paper = Paper.objects.get(pk=paper)

    try:
        event = build_paper_event(paper, interaction, item, user)
    except (KeyError, TypeError) as e:
        return Response(
            f'`item` in post body data was likely malformed: {e}',
            status=400
        )

    response = get_event_hit_response(*event, utc_datetime)
    if response.ok:
        return Response('Success', status=200)
    return Response('Failed', status=500)


def build_paper_event(paper, interaction, item, user):
    category = 'Paper'

    action = f'{item["name"].capitalize()} {interaction.capitalize()}'
    if paper is not None:
        action += f' Paper:{paper.id}'

    label = f'{item["value"].capitalize()}'
    if user is not None:
        if type(user) is str:
            user_id = user
        else:
            user_id = user.id
        label += f' User:{user_id}'

    return (category, action, label)
