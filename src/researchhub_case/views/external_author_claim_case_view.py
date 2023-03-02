import json

from boto3.session import Session
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from researchhub.settings import (
    AWS_ACCESS_KEY_ID,
    AWS_S3_REGION_NAME,
    AWS_SCHOLARLY_LAMBDA,
    AWS_SECRET_ACCESS_KEY,
)
from researchhub_case.constants.case_constants import EXTERNAL_AUTHOR_CLAIM
from researchhub_case.models import ExternalAuthorClaimCase
from researchhub_case.serializers import (
    DynamicExternalAuthorClaimCaseSerializer,
    ExternalAuthorClaimCaseSerializer,
)
from rh_scholarly.lambda_handler import SEARCH_FOR_AUTHORS
from user.models import Action, User
from user.permissions import IsModerator
from utils.http import POST
from utils.permissions import PostOnly


class ExternalAuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated & (PostOnly | IsModerator)]
    queryset = ExternalAuthorClaimCase.objects.all()
    serializer_class = ExternalAuthorClaimCaseSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status"]

    def get_serializer_class(self):
        if self.request.method == POST:
            return self.serializer_class

        def _get_dynamic_serializer(*args, **kwargs):
            dynamic_context = {
                "cse_darc_get_requestor": {"_include_fields": ("author_profile", "id")},
                "usr_dus_get_author_profile": {
                    "_include_fields": ("first_name", "last_name", "profile_image")
                },
            }
            if "context" in kwargs:
                kwargs["context"].update(dynamic_context)
            else:
                kwargs["context"] = dynamic_context
            return DynamicExternalAuthorClaimCaseSerializer(
                *args, **kwargs, _exclude_fields=("creator", "moderator")
            )

        return _get_dynamic_serializer

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        claim_data = {
            "case_type": EXTERNAL_AUTHOR_CLAIM,
            "requestor": user.id,
            "creator": user.id,
            **data,
        }
        serializer = self.get_serializer(data=claim_data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()

        Action.objects.create(item=obj, user=user, display=False)
        return Response(serializer.data, status=200)

    @action(
        detail=False,
        methods=[POST],
    )
    def search_scholarly_by_name(self, request):
        data = request.data
        lambda_body = {SEARCH_FOR_AUTHORS: [data.get("name", "")]}
        data_bytes = json.dumps(lambda_body)
        session = Session(
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_S3_REGION_NAME,
        )
        lambda_client = session.client(
            service_name="lambda", region_name=AWS_S3_REGION_NAME
        )
        response = lambda_client.invoke(
            FunctionName=AWS_SCHOLARLY_LAMBDA,
            InvocationType="RequestResponse",
            Payload=data_bytes,
        )
        response_data = response.get("Payload", None)
        if response_data:
            response_data = json.loads(response_data.read())
        return Response(response_data, status=200)

    @action(
        detail=True, methods=[POST], permission_classes=[IsAuthenticated, IsModerator]
    )
    def approve_claim(self, request, pk=None):
        claim = self.get_object()
        claim.approve_google_scholar()
        serializer = self.get_serializer(claim)
        return Response(serializer.data, status=200)
