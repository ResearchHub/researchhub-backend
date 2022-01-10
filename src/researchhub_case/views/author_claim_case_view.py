from django.http.response import HttpResponseBadRequest
from researchhub_case.constants.case_constants import (
    ALLOWED_VALIDATION_ATTEMPT_COUNT, INITIATED, INVALIDATED, OPEN
)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated, AllowAny
)

from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from utils.http import POST


class AuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [
        AllowAny,
    ]
    queryset = AuthorClaimCase.objects.all().order_by("-created_date")
    serializer_class = AuthorClaimCaseSerializer

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except Exception as error:
            return Response(str(error.args), status=400)


@api_view(http_method_names=[POST])
@permission_classes([IsAuthenticated])
def validate_user_request_email(request):
    try:
        validation_token = request.data.get('token')
        target_case = AuthorClaimCase.objects.get(
            status=INITIATED,
            validation_token=validation_token
        )
        invalidation_result = check_and_invalidate_case(
            target_case,
            request.user
        )
        if (invalidation_result is not None):
            return invalidation_result
        
        target_case.status = OPEN
        target_case.save()
        return Response('SUCCESS',  status=200)

    except (KeyError, TypeError) as e:
        return Response(e, status=400)


def check_and_invalidate_case(target_case, current_user):
    attempt_count = target_case.validation_attempt_count
    if (ALLOWED_VALIDATION_ATTEMPT_COUNT < attempt_count):
        target_case.status = INVALIDATED
        target_case.save()
        return Response('DENIED_TOO_MANY_ATTEMPS', status=400)
        
    if (target_case.requestor.id != current_user.id):
        target_case.validation_attempt_count += 1
        target_case.save()
        return Response('DENIED_WRONG_USER', status=400)
