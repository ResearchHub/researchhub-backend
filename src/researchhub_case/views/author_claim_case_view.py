import json 

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from researchhub_case.utils.author_claim_case_utils import (
    decode_validation_token
)
from utils.http import POST


class AuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [
        # TODO: calvinhlee - add more privacy later
        AllowAny
    ]
    queryset = AuthorClaimCase.objects.all()
    serializer_class = AuthorClaimCaseSerializer


# TODO: calvinhlee - add permissions class here
@api_view(http_method_names=[POST])
@permission_classes([AllowAny])
def validate_user_request_email(request):
    try:
        print(['*********** RECEIVED DATA: ', request.data])
        decoded_client_token_json = json.load(
            decode_validation_token(
                request.data.get("token")
            )
        )
        print("DECODED: ", decoded_client_token_json)
        validation_token = decoded_client_token_json["token"]
        target_case = AuthorClaimCase.objects.get(
            validation_token=validation_token
        )
        curr_user = request.user
        print("curr_user: ", curr_user)
        if (target_case.requestor__id != curr_user.id):
            return Response("YO", status=400)

        return Response('Success',  status=200)
    except (KeyError, TypeError) as e:
        return Response(e, status=400)

