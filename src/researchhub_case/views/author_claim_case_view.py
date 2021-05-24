from researchhub_case.constants.case_constants import (
    ALLOWED_VALIDATION_ATTEMPT_COUNT, INITIATED, INVALIDATED, OPEN
)
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated
)

# from researchhub_case.permissions import IsModerator
from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from utils.http import POST


class AuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [
        # TODO: calvinhlee - look into this
        AllowAny,
    ]
    queryset = AuthorClaimCase.objects.all()
    serializer_class = AuthorClaimCaseSerializer


@api_view(http_method_names=[POST])
@permission_classes([IsAuthenticated])
def validate_user_request_email(request):
    try:
        validation_token = request.data.get('token')
        target_case = AuthorClaimCase.objects.get(
            status=INITIATED,
            validation_token=validation_token
        )
        invalidation_result = check_and_invalidate_case(target_case)
        if (invalidation_result is not None):
            return invalidation_result

        target_case.validation_attempt_count += 1
        target_case.save()
        print("TOKEN: ", validation_token)

        curr_user = request.user
        if (target_case.requestor.id != curr_user.id):
            return Response('DENIED_WRONG_USER', status=400)
        else:
            target_case.status = OPEN
            target_case.save()
            return Response('SUCCESS',  status=200)

    except (KeyError, TypeError) as e:
        return Response(e, status=400)


def check_and_invalidate_case(target_case):
    attempt_count = target_case.validation_attempt_count
    if (ALLOWED_VALIDATION_ATTEMPT_COUNT < attempt_count):
        target_case.status = INVALIDATED
        target_case.save()
        return Response("DENIED_TOO_MANY_ATTEMPS", status=400)
