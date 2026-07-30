from typing import override

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from mailing_list.serializers import EmailUnsubscribeSerializer
from mailing_list.services import EmailSubscriptionService, InvalidUnsubscribeCodeError


class EmailUnsubscribeView(APIView):
    """
    Endpoint for unsubscribing an email address using a signed code.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = EmailUnsubscribeSerializer

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._subscription_service = EmailSubscriptionService()

    def post(self, request: Request) -> Response:
        payload = self._request_payload(request)
        serializer = self.serializer_class(data=payload)
        serializer.is_valid(raise_exception=True)

        try:
            self._subscription_service.unsubscribe(serializer.validated_data["code"])
        except InvalidUnsubscribeCodeError as e:
            raise serializers.ValidationError(
                {"code": ["Invalid unsubscribe code."]}
            ) from e

        return Response(
            {"detail": "Email address unsubscribed."},
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _request_payload(request: Request) -> dict:
        """
        Read the code from JSON/form data or the query string.

        One-click unsubscribe clients POST an otherwise unrelated form body to
        the URL from the List-Unsubscribe header, so the code may live in the
        query string.
        """
        payload = dict(request.data.items()) if hasattr(request.data, "items") else {}
        if "code" not in payload and request.query_params.get("code"):
            payload["code"] = request.query_params["code"]
        return payload
