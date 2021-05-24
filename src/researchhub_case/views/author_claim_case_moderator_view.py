from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from utils.http import GET, POST

from researchhub_case.constants.case_constants import (
    APPROVED, DENIED, INVALIDATED, NULLIFIED, OPEN,
)
from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from researchhub_case.permissions import IsModerator


@api_view(http_method_names=[GET, POST])
@permission_classes([IsModerator])
def handle_author_claim_cases_for_mods(request):
    if (request.method == "GET"):
        return get_author_claim_cases_for_mods(request)
    else:
        return post_author_claim_cases_for_mods(request)


def get_author_claim_cases_for_mods(request):
    # TODO: calvinhlee - paginate this
    try:
        case_status = request.query_params.get('case_status')
        if (case_status == 'CLOSED'):
            case_query_status = [APPROVED, DENIED, INVALIDATED, NULLIFIED]
        elif (case_status == 'OPEN'):
            case_query_status = [OPEN]
        else:
            return Response('Bad case status', status=400)

        target_case_set = AuthorClaimCase.objects.filter(
            status__in=case_query_status
        )
        serialized_result = AuthorClaimCaseSerializer(
          target_case_set, many=True
        )
        return Response(data=serialized_result.data, status=200)
    except (KeyError, TypeError) as e:
        return Response(e, status=400)


def post_author_claim_cases_for_mods(request):
    try:
        request_data = request.data
        print("RESUQEST_DATA: ", request_data)
        update_status = request_data['update_status']
        if (update_status not in ['APPROVED', 'DENIED']):
            return Response('Base update status', status=400)

        case_id = request_data['case_id']
        case = AuthorClaimCase.objects.get(id=case_id, status=OPEN)
        case.status = APPROVED if update_status == "APPROVED" else DENIED
        case.save()
        return Response('Success', status=200)
    except (KeyError, TypeError) as e:
        return Response(e, status=400)


@api_view(http_method_names=[GET])
@permission_classes([IsModerator])
def get_author_claim_counts_for_mods(request):
    try:
        close_count = AuthorClaimCase.objects.filter(
            status__in=[APPROVED, DENIED, INVALIDATED, NULLIFIED]
        ).count()
        open_count = AuthorClaimCase.objects.filter(
            status__in=[OPEN]
        ).count()
        return Response(data={
          'closed_count': close_count,
          'open_count': open_count
        }, status=200)
    except (KeyError, TypeError) as e:
        return Response(e, status=400)
